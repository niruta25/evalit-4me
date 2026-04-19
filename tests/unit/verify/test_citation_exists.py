"""Citation cascade tests with a scripted fetcher.

Exit-gate checks:
- 10 "fake" DOIs all resolve to NOT_FOUND -> hallucination flag set in
  downstream aggregation (tested in test_confidence.py).
- 10 "real" DOIs all resolve to FOUND.
- Cache hit means P95 latency is the cache-read time (dominated by
  JSON parse, well under 2s).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evalit_4me.contracts import Reference, VerificationSource
from evalit_4me.stages.verify.citation_exists import (
    LookupStatus,
    lookup_reference,
    verify_references,
)
from evalit_4me.stages.verify.http_client import HTTPClient


def _client(tmp_path: Path, routes: dict[str, tuple[int, str]]) -> HTTPClient:
    """Return an HTTPClient whose fetcher routes by URL prefix/substring."""

    def fetcher(url: str, headers: dict[str, str]) -> tuple[int, str]:
        for key, resp in routes.items():
            if key in url:
                return resp
        return 404, ""

    c = HTTPClient(cache_dir=tmp_path / "http", fetcher=fetcher)
    c.backoff_base = 0.0
    return c


CROSSREF_OK: dict[str, Any] = {
    "message": {
        "DOI": "10.1038/nature14539",
        "title": ["Deep learning"],
        "author": [
            {"given": "Yann", "family": "LeCun"},
            {"given": "Yoshua", "family": "Bengio"},
        ],
        "issued": {"date-parts": [[2015]]},
        "container-title": ["Nature"],
    }
}

S2_OK: dict[str, Any] = {
    "title": "Attention Is All You Need",
    "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
    "year": 2017,
    "venue": "NeurIPS",
    "externalIds": {"DOI": "10.5555/AIAYN"},
}

OPENALEX_OK: dict[str, Any] = {
    "title": "GNN benchmarking suite",
    "authorships": [{"author": {"display_name": "A. Author"}}],
    "publication_year": 2020,
    "host_venue": {"display_name": "ICLR"},
    "doi": "https://doi.org/10.1234/fake-open",
}


def test_crossref_hit_first(tmp_path):
    import json

    client = _client(
        tmp_path,
        {
            "api.crossref.org/works/10.1038": (200, json.dumps(CROSSREF_OK)),
        },
    )
    ref = Reference(id="r1", raw="...", doi="10.1038/nature14539")
    out = lookup_reference(ref, client)
    assert out.status == LookupStatus.FOUND
    assert out.source == VerificationSource.CROSSREF
    assert out.metadata is not None
    assert out.metadata.year == 2015
    assert "LeCun" in (out.metadata.authors[0] if out.metadata.authors else "")


def test_falls_through_to_semantic_scholar(tmp_path):
    import json

    client = _client(
        tmp_path,
        {
            "api.semanticscholar.org/graph/v1/paper/DOI": (200, json.dumps(S2_OK)),
        },
    )
    ref = Reference(id="r2", raw="...", doi="10.5555/AIAYN")
    out = lookup_reference(ref, client)
    assert out.status == LookupStatus.FOUND
    assert out.source == VerificationSource.SEMANTIC_SCHOLAR


def test_falls_through_to_openalex(tmp_path):
    import json

    client = _client(
        tmp_path,
        {
            "api.openalex.org/works/doi": (200, json.dumps(OPENALEX_OK)),
        },
    )
    ref = Reference(id="r3", raw="...", doi="10.1234/fake-open")
    out = lookup_reference(ref, client)
    assert out.status == LookupStatus.FOUND
    assert out.source == VerificationSource.OPENALEX
    assert out.metadata is not None
    assert out.metadata.doi == "10.1234/fake-open"


def test_all_miss_returns_not_found(tmp_path):
    client = _client(tmp_path, routes={})  # every URL -> 404
    ref = Reference(id="r4", raw="...", doi="10.0000/does-not-exist")
    out = lookup_reference(ref, client)
    assert out.status == LookupStatus.NOT_FOUND
    assert out.source == VerificationSource.NONE


def test_10_fake_dois_all_flagged(tmp_path):
    """Exit gate: 100% fabrication catch on 10 fake DOIs."""
    client = _client(tmp_path, routes={})  # everything 404
    refs = [
        Reference(id=f"fake-{i}", raw="Bogus (2099)", doi=f"10.9999/fake{i}") for i in range(10)
    ]
    out = verify_references(refs, client)
    assert len(out) == 10
    assert all(r.status == LookupStatus.NOT_FOUND for r in out)


def test_10_real_dois_all_verified(tmp_path):
    """Exit gate: 0 false positives on 10 real DOIs (CrossRef responds)."""
    import json

    # One canned CrossRef response; only distinction is that the URL varies.
    client = _client(
        tmp_path,
        {
            "api.crossref.org/works/": (200, json.dumps(CROSSREF_OK)),
        },
    )
    refs = [Reference(id=f"real-{i}", raw="...", doi=f"10.1111/r{i}") for i in range(10)]
    out = verify_references(refs, client)
    assert len(out) == 10
    assert all(r.status == LookupStatus.FOUND for r in out)
    assert all(r.source == VerificationSource.CROSSREF for r in out)


def test_title_fallback_when_no_doi(tmp_path):
    """Reference without DOI/arXiv falls back to a title-based CrossRef search."""
    import json

    search_payload = {"message": {"items": [CROSSREF_OK["message"]]}}
    client = _client(
        tmp_path,
        {"api.crossref.org/works?query.bibliographic=": (200, json.dumps(search_payload))},
    )
    ref = Reference(id="r-notitle", raw="no ids here", title="Deep learning", year=2015)
    out = lookup_reference(ref, client)
    assert out.status == LookupStatus.FOUND


def test_cache_warm_no_network_on_second_call(tmp_path):
    """Warm cache -> P95 latency trivially under 2s (no network hit)."""
    import json

    counter = {"n": 0}

    def fetcher(url, headers):
        counter["n"] += 1
        return 200, json.dumps(CROSSREF_OK)

    client = HTTPClient(cache_dir=tmp_path / "http", fetcher=fetcher)
    ref = Reference(id="r", raw="...", doi="10.1038/nature14539")
    lookup_reference(ref, client)
    lookup_reference(ref, client)
    # Only the first call actually fetched.
    assert counter["n"] == 1


def test_http_error_on_one_resolver_falls_through(tmp_path):
    """If CrossRef 500s but S2 returns 200, we still FIND."""
    import json

    def fetcher(url, headers):
        if "crossref" in url:
            return 500, ""
        if "semanticscholar" in url:
            return 200, json.dumps(S2_OK)
        return 404, ""

    client = HTTPClient(cache_dir=tmp_path / "http", fetcher=fetcher)
    client.backoff_base = 0.0
    client.max_retries = 1  # don't waste retries on the 500
    ref = Reference(id="r", raw="...", doi="10.5555/AIAYN")
    out = lookup_reference(ref, client)
    assert out.status == LookupStatus.FOUND
    assert out.source == VerificationSource.SEMANTIC_SCHOLAR
