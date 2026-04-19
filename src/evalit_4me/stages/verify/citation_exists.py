"""Citation-existence cascade: CrossRef -> Semantic Scholar -> OpenAlex.

Order of resolvers is chosen by signal quality: CrossRef is the most
authoritative on DOIs, Semantic Scholar fills gaps (especially for
preprints and arXiv-only papers), OpenAlex is the safety net with the
broadest coverage but the highest metadata variance.

Lookup-key priority per reference:
    DOI  ->  arXiv ID  ->  title + first author surname

If all three resolvers miss, we mark the citation NOT_FOUND — this is the
hallucination signal that Chunk 1.6's exit gate cares about (100% catch
on fake DOIs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import quote

from evalit_4me.contracts import Reference, VerificationSource
from evalit_4me.stages.verify.http_client import HTTPClient, HTTPError


class LookupStatus(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    ERROR = "ERROR"


@dataclass
class ExternalMetadata:
    """Normalized view of what the external API returned."""

    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None


@dataclass
class CitationLookup:
    """Per-reference lookup outcome."""

    reference_id: str
    status: LookupStatus
    source: VerificationSource
    metadata: ExternalMetadata | None = None
    error: str | None = None


CROSSREF_URL = "https://api.crossref.org/works/{doi}"
CROSSREF_SEARCH_URL = "https://api.crossref.org/works?query.bibliographic={q}&rows=1"
S2_DOI_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=title,authors,year,venue,externalIds"
S2_ARXIV_URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv}?fields=title,authors,year,venue,externalIds"
S2_SEARCH_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/search?query={q}"
    "&limit=1&fields=title,authors,year,venue,externalIds"
)
OPENALEX_DOI_URL = "https://api.openalex.org/works/doi:{doi}"
OPENALEX_SEARCH_URL = "https://api.openalex.org/works?search={q}&per-page=1"


def lookup_reference(ref: Reference, client: HTTPClient) -> CitationLookup:
    """Run the resolver cascade for a single reference.

    Returns FOUND on the first resolver that resolves the reference, else
    NOT_FOUND. A resolver raising `HTTPError` downgrades it to "no hit"
    (we continue the cascade); a transport failure on ALL resolvers
    results in ERROR.
    """
    errors: list[str] = []
    for resolver, source in _RESOLVERS:
        try:
            meta = resolver(ref, client)
        except HTTPError as exc:
            errors.append(f"{source}: {exc}")
            continue
        if meta is not None:
            return CitationLookup(
                reference_id=ref.id,
                status=LookupStatus.FOUND,
                source=source,
                metadata=meta,
            )
    if errors and len(errors) == len(_RESOLVERS):
        return CitationLookup(
            reference_id=ref.id,
            status=LookupStatus.ERROR,
            source=VerificationSource.NONE,
            error="; ".join(errors),
        )
    return CitationLookup(
        reference_id=ref.id,
        status=LookupStatus.NOT_FOUND,
        source=VerificationSource.NONE,
    )


def verify_references(refs: list[Reference], client: HTTPClient) -> list[CitationLookup]:
    """Batch wrapper. Order-preserving. No parallelism — caching +
    sequential keeps the fairness story simple for now."""
    return [lookup_reference(r, client) for r in refs]


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------


def _crossref(ref: Reference, client: HTTPClient) -> ExternalMetadata | None:
    if ref.doi:
        data = client.get_json(CROSSREF_URL.format(doi=quote(ref.doi, safe="")))
        if data is not None:
            return _from_crossref(data.get("message", {}))
    # Title-based fallback.
    query = _title_author_query(ref)
    if not query:
        return None
    data = client.get_json(CROSSREF_SEARCH_URL.format(q=quote(query)))
    if data is None:
        return None
    items = (data.get("message") or {}).get("items") or []
    if not items:
        return None
    return _from_crossref(items[0])


def _from_crossref(item: dict[str, Any]) -> ExternalMetadata:
    title = _first(item.get("title"))
    authors = [
        " ".join(filter(None, [a.get("given"), a.get("family")])).strip()
        for a in item.get("author", [])
        if isinstance(a, dict)
    ]
    year = _first_year(item.get("issued", {}).get("date-parts"))
    venue = _first(item.get("container-title"))
    return ExternalMetadata(
        title=title,
        authors=[a for a in authors if a],
        year=year,
        venue=venue,
        doi=item.get("DOI"),
    )


def _semantic_scholar(ref: Reference, client: HTTPClient) -> ExternalMetadata | None:
    if ref.doi:
        data = client.get_json(S2_DOI_URL.format(doi=quote(ref.doi, safe="")))
        if data is not None:
            return _from_s2(data)
    if ref.arxiv_id:
        data = client.get_json(S2_ARXIV_URL.format(arxiv=quote(ref.arxiv_id, safe="")))
        if data is not None:
            return _from_s2(data)
    query = _title_author_query(ref)
    if not query:
        return None
    data = client.get_json(S2_SEARCH_URL.format(q=quote(query)))
    if data is None:
        return None
    hits = data.get("data") or []
    if not hits:
        return None
    return _from_s2(hits[0])


def _from_s2(item: dict[str, Any]) -> ExternalMetadata:
    title = item.get("title")
    authors = [
        a.get("name") for a in item.get("authors", []) if isinstance(a, dict) and a.get("name")
    ]
    year = item.get("year")
    venue = item.get("venue") or None
    external = item.get("externalIds") or {}
    doi = external.get("DOI")
    return ExternalMetadata(
        title=title,
        authors=[a for a in authors if a],
        year=int(year) if isinstance(year, int) else None,
        venue=venue,
        doi=doi,
    )


def _openalex(ref: Reference, client: HTTPClient) -> ExternalMetadata | None:
    if ref.doi:
        data = client.get_json(OPENALEX_DOI_URL.format(doi=quote(ref.doi, safe="")))
        if data is not None:
            return _from_openalex(data)
    query = _title_author_query(ref)
    if not query:
        return None
    data = client.get_json(OPENALEX_SEARCH_URL.format(q=quote(query)))
    if data is None:
        return None
    results = data.get("results") or []
    if not results:
        return None
    return _from_openalex(results[0])


def _from_openalex(item: dict[str, Any]) -> ExternalMetadata:
    title = item.get("title") or item.get("display_name")
    authors = []
    for aship in item.get("authorships", []) or []:
        if isinstance(aship, dict):
            author = aship.get("author") or {}
            name = author.get("display_name")
            if name:
                authors.append(name)
    year = item.get("publication_year")
    venue = None
    host_venue = item.get("host_venue") or item.get("primary_location", {}).get("source") or {}
    if isinstance(host_venue, dict):
        venue = host_venue.get("display_name")
    doi = item.get("doi")
    if isinstance(doi, str) and doi.startswith("https://doi.org/"):
        doi = doi.removeprefix("https://doi.org/")
    return ExternalMetadata(
        title=title,
        authors=authors,
        year=int(year) if isinstance(year, int) else None,
        venue=venue,
        doi=doi,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_RESOLVERS = (
    (_crossref, VerificationSource.CROSSREF),
    (_semantic_scholar, VerificationSource.SEMANTIC_SCHOLAR),
    (_openalex, VerificationSource.OPENALEX),
)


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        return value[0] if value else None
    return value if isinstance(value, str) else None


def _first_year(date_parts: Any) -> int | None:
    if not isinstance(date_parts, list) or not date_parts:
        return None
    first = date_parts[0]
    if isinstance(first, list) and first and isinstance(first[0], int):
        return first[0]
    return None


def _title_author_query(ref: Reference) -> str | None:
    if ref.title:
        base = ref.title
        if ref.authors:
            base = f"{base} {ref.authors[0]}"
        return base
    # Raw reference text as last resort.
    return ref.raw.strip() or None
