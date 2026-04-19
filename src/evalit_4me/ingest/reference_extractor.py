"""Extract structured `Reference` entries from a references section.

Downstream (Chunk 1.6) looks up each reference against CrossRef / Semantic
Scholar / OpenAlex. The extractor's job is to recover enough signal for
that lookup to succeed — in priority order: DOI > arXiv ID > title + year.
Perfect metadata recovery is not the goal; recall is.
"""

from __future__ import annotations

import re

from evalit_4me.contracts import Reference

# DOI regex: CrossRef's published pattern, slightly relaxed.
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)

# arXiv ID: post-2007 form (YYMM.NNNNN) and legacy form (category/YYMMNNN).
ARXIV_NEW_RE = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b")
ARXIV_OLD_RE = re.compile(r"\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\b", re.IGNORECASE)

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# Leading marker like "[12]", "(12)", "12.", or "*" / "-".
LEADING_MARKER_RE = re.compile(r"^(?:\[\d+\]|\(\d+\)|\d+\.|\*|-)\s+")


def extract_references(references_text: str) -> list[Reference]:
    """Parse a references section body into a list of `Reference` objects.

    Each paragraph (blank-line separated) OR each numbered line is one
    reference. Continuation lines (indented or not prefixed with a marker)
    are folded into the previous entry.
    """
    if not references_text.strip():
        return []

    raw_entries = _split_entries(references_text)
    out: list[Reference] = []
    for idx, raw in enumerate(raw_entries):
        cleaned = LEADING_MARKER_RE.sub("", raw).strip()
        if not cleaned:
            continue
        ref = _build_reference(ref_id=f"ref-{idx + 1}", raw=cleaned)
        out.append(ref)
    return out


def _split_entries(text: str) -> list[str]:
    """Split a references block into one string per entry.

    Strategy: collect lines, flush a new entry whenever we see a line that
    starts with a numbered/bulleted marker OR the previous entry ended with
    a sentence-final period and the current line starts with a capital.
    Falls back to blank-line splitting if no markers are present.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    # Strip surrounding blank lines.
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return []

    has_markers = any(LEADING_MARKER_RE.match(ln) for ln in lines)

    if has_markers:
        entries: list[str] = []
        current: list[str] = []
        for ln in lines:
            if LEADING_MARKER_RE.match(ln):
                if current:
                    entries.append(" ".join(current).strip())
                current = [ln]
            else:
                if not ln.strip():
                    continue
                current.append(ln.strip())
        if current:
            entries.append(" ".join(current).strip())
        return entries

    # No markers — fall back to blank-line paragraphs.
    chunks: list[list[str]] = []
    buf: list[str] = []
    for ln in lines:
        if not ln.strip():
            if buf:
                chunks.append(buf)
                buf = []
        else:
            buf.append(ln.strip())
    if buf:
        chunks.append(buf)
    return [" ".join(c) for c in chunks]


def _build_reference(*, ref_id: str, raw: str) -> Reference:
    doi = _find_doi(raw)
    arxiv_id = _find_arxiv(raw)
    year = _find_year(raw)
    title = _guess_title(raw, year=year)
    authors = _guess_authors(raw, title=title)
    return Reference(
        id=ref_id,
        raw=raw,
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        arxiv_id=arxiv_id,
    )


def _find_doi(text: str) -> str | None:
    m = DOI_RE.search(text)
    if not m:
        return None
    # Strip trailing punctuation commonly glued onto DOIs.
    return m.group(0).rstrip(".,;)")


_VERSION_SUFFIX_RE = re.compile(r"v\d+$", re.IGNORECASE)


def _find_arxiv(text: str) -> str | None:
    # Prefer "arXiv:XXXX.XXXXX" capture if marker present.
    explicit = re.search(
        r"arxiv[:\s]+((?:\d{4}\.\d{4,5})(?:v\d+)?|"
        r"(?:[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)",
        text,
        re.IGNORECASE,
    )
    if explicit:
        return _VERSION_SUFFIX_RE.sub("", explicit.group(1))
    m = ARXIV_NEW_RE.search(text)
    if m:
        return m.group(1)
    m = ARXIV_OLD_RE.search(text)
    if m:
        return m.group(1)
    return None


def _find_year(text: str) -> int | None:
    m = YEAR_RE.search(text)
    return int(m.group(0)) if m else None


def _guess_title(text: str, *, year: int | None) -> str | None:
    """Heuristic title extraction.

    Common academic reference shape:
        Author, A., Author, B. (YEAR). Title of the paper. Venue, ...
    We split on the first occurrence of "(YEAR)." or "YEAR." after authors
    and take the next sentence up to the following "." or "In " / "arXiv".
    """
    if year is None:
        return _fallback_title(text)

    year_str = str(year)
    # Locate the year and the period following it.
    idx = text.find(year_str)
    if idx == -1:
        return _fallback_title(text)

    after = text[idx + len(year_str) :]
    # Drop leading punctuation like "). " or "."
    after = re.sub(r"^[).,\s]*", "", after)
    if not after:
        return _fallback_title(text)

    # Title ends at the next period followed by space + capital, "In ", or "arXiv".
    end_match = re.search(
        r"\.(?=\s+(?:[A-Z]|In\b|arXiv\b|Proceedings\b|Advances\b|https?:))",
        after,
    )
    title = after[: end_match.start()] if end_match else after
    title = title.strip(" .")
    return title or _fallback_title(text)


def _fallback_title(text: str) -> str | None:
    # As a last resort, return the raw reference (truncated) so downstream
    # lookup has *something* to work with.
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    return collapsed[:200]


def _guess_authors(text: str, *, title: str | None) -> list[str]:
    """Authors are the prefix before the first "(YEAR)" or year.

    Return an empty list on failure — downstream CrossRef lookup can recover
    authors from the DOI or title match. We don't invent structure.
    """
    year_m = YEAR_RE.search(text)
    if not year_m:
        return []
    prefix = text[: year_m.start()].strip().strip("(.,")
    if not prefix or (title and prefix == title):
        return []
    # Split on " and " or ", " heuristically. Keep whole names.
    parts = re.split(r",\s+(?=[A-Z])|\s+and\s+", prefix)
    return [p.strip(" .,") for p in parts if p.strip(" .,")]
