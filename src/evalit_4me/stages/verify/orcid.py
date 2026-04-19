"""Stage 2c-b: ORCID author lookup.

Given a paper's authors, resolve each to an ORCID iD when possible. Match
confidence is returned so the reviewer/dashboard can distinguish
"unambiguous match" from "plausible guess".

We use the ORCID public v3 expanded-search endpoint which returns
structured author hits. No auth required for public data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

from evalit_4me.stages.verify.http_client import HTTPClient

ORCID_SEARCH_URL = "https://pub.orcid.org/v3.0/expanded-search/?q={q}&rows=3"

ORCID_ID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


@dataclass(frozen=True)
class OrcidMatch:
    queried_name: str
    orcid_id: str | None
    matched_name: str | None
    institution: str | None
    confidence: float  # 0..1


def lookup_author(name: str, client: HTTPClient) -> OrcidMatch:
    """Return the best ORCID match for `name`, or a null-match if none found."""
    query = name.strip()
    if not query:
        return OrcidMatch(
            queried_name=name, orcid_id=None, matched_name=None, institution=None, confidence=0.0
        )
    url = ORCID_SEARCH_URL.format(q=quote(query))
    data = client.get_json(url, extra_headers={"Accept": "application/json"})
    if not data:
        return OrcidMatch(
            queried_name=name, orcid_id=None, matched_name=None, institution=None, confidence=0.0
        )
    results = data.get("expanded-result") or []
    if not results:
        return OrcidMatch(
            queried_name=name, orcid_id=None, matched_name=None, institution=None, confidence=0.0
        )
    best = _best_match(query, results)
    return best


def lookup_authors(names: list[str], client: HTTPClient) -> dict[str, OrcidMatch]:
    return {n: lookup_author(n, client) for n in names}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _best_match(queried: str, hits: list[dict]) -> OrcidMatch:
    q_tokens = _tokens(queried)
    best_score = 0.0
    best_hit: dict | None = None
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        name = _candidate_name(hit)
        if not name:
            continue
        score = _name_similarity(q_tokens, _tokens(name))
        if score > best_score:
            best_score = score
            best_hit = hit
    if best_hit is None or best_score < 0.34:
        return OrcidMatch(
            queried_name=queried, orcid_id=None, matched_name=None, institution=None, confidence=0.0
        )

    orcid_id = best_hit.get("orcid-id")
    if not isinstance(orcid_id, str) or not ORCID_ID_RE.match(orcid_id):
        orcid_id = None

    institutions = best_hit.get("institution-name") or []
    institution = institutions[0] if isinstance(institutions, list) and institutions else None
    if isinstance(institution, dict):
        institution = institution.get("value")
    matched_name = _candidate_name(best_hit)

    return OrcidMatch(
        queried_name=queried,
        orcid_id=orcid_id,
        matched_name=matched_name,
        institution=institution,
        confidence=round(best_score, 4),
    )


def _candidate_name(hit: dict) -> str | None:
    given = hit.get("given-names") or ""
    family = hit.get("family-names") or ""
    full = f"{given} {family}".strip()
    if full:
        return full
    return hit.get("credit-name") or None


def _tokens(name: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z\-']+", name) if len(t) > 1}


def _name_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    # Bias toward recall on the query side — if the query's tokens are all
    # present in the hit, we match.
    recall = intersection / len(a)
    jaccard = intersection / len(a | b)
    return max(recall, jaccard)
