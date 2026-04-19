"""Metadata match scoring: how well does what the paper cited line up
with what the external resolver returned?

Four sub-scores, each in [0, 1]:

    author_score  — best Jaccard-ish overlap on surnames
    year_score    — exact/near/off
    title_score   — normalized token overlap (Jaccard) on lowercased alnum tokens
    venue_score   — substring match on the main venue token

Overall match = weighted mean (weights match paper §4.2: title dominates).
A citation with overall >= 0.6 is considered `match_ok = True`. Below that
the citation is flagged for reviewer attention even though the paper was
found — this catches "DOI resolves but to a different paper" cases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from evalit_4me.contracts import Reference
from evalit_4me.stages.verify.citation_exists import ExternalMetadata

_WORD_RE = re.compile(r"[a-z0-9]+")

WEIGHTS = {"title": 0.5, "author": 0.25, "year": 0.15, "venue": 0.10}
MATCH_THRESHOLD = 0.6


@dataclass(frozen=True)
class MetadataMatch:
    author_score: float
    year_score: float
    title_score: float
    venue_score: float
    overall: float
    match_ok: bool
    mismatches: tuple[str, ...] = ()


def compare_metadata(ref: Reference, found: ExternalMetadata) -> MetadataMatch:
    author = _score_authors(ref.authors, found.authors)
    year = _score_year(ref.year, found.year)
    title = _score_title(ref.title, found.title)
    venue = _score_venue(ref.venue, found.venue)

    overall = (
        WEIGHTS["title"] * title
        + WEIGHTS["author"] * author
        + WEIGHTS["year"] * year
        + WEIGHTS["venue"] * venue
    )
    mismatches: list[str] = []
    # Require at least some overlap on title, regardless of overall score.
    # A perfect year + author with zero title overlap usually means the
    # external resolver matched the wrong paper.
    if ref.title and title < 0.2:
        mismatches.append("title")
    if ref.year and found.year and abs(ref.year - found.year) > 1:
        mismatches.append("year")
    if ref.authors and author < 0.2:
        mismatches.append("author")

    match_ok = overall >= MATCH_THRESHOLD and "title" not in mismatches
    return MetadataMatch(
        author_score=author,
        year_score=year,
        title_score=title,
        venue_score=venue,
        overall=overall,
        match_ok=match_ok,
        mismatches=tuple(mismatches),
    )


# ---------------------------------------------------------------------------
# Sub-scoring
# ---------------------------------------------------------------------------


def _score_title(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0 if (a or b) else 1.0
    return _jaccard(_tokens(a), _tokens(b))


def _score_authors(a: list[str], b: list[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    surnames_a = {_surname(x) for x in a if x}
    surnames_b = {_surname(x) for x in b if x}
    if not surnames_a or not surnames_b:
        return 0.0
    intersection = surnames_a & surnames_b
    union = surnames_a | surnames_b
    return len(intersection) / len(union) if union else 0.0


def _score_year(a: int | None, b: int | None) -> float:
    if a is None or b is None:
        return 1.0 if a is None and b is None else 0.0
    delta = abs(a - b)
    if delta == 0:
        return 1.0
    if delta == 1:
        return 0.8
    if delta <= 3:
        return 0.4
    return 0.0


def _score_venue(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 1.0 if not a and not b else 0.0
    a_norm = a.strip().lower()
    b_norm = b.strip().lower()
    if a_norm == b_norm:
        return 1.0
    if a_norm in b_norm or b_norm in a_norm:
        return 0.7
    overlap = _jaccard(_tokens(a_norm), _tokens(b_norm))
    return overlap


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD_RE.findall(text.lower()) if t}


def _surname(name: str) -> str:
    """Extract surname from a name formatted as either "First Last" or
    "Last, First" (incl. initials-only first names like "LeCun, Y.")."""
    stripped = name.strip()
    if not stripped:
        return ""
    if "," in stripped:
        # "Last, First" or "Last, F." — surname is the prefix.
        surname_part = stripped.split(",", 1)[0]
    else:
        # "First Last" or "First M. Last" — surname is the last whitespace token.
        tokens = stripped.split()
        surname_part = tokens[-1] if tokens else ""
    return re.sub(r"[^\w]", "", surname_part).lower()


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
