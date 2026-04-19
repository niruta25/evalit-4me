"""Aggregation: lookups + metadata matches + temporal -> ClaimLedger."""

from __future__ import annotations

from evalit_4me.contracts import (
    Claim,
    ClaimType,
    Severity,
    SourceSpan,
    VerificationSource,
)
from evalit_4me.stages.verify.citation_exists import (
    CitationLookup,
    ExternalMetadata,
    LookupStatus,
)
from evalit_4me.stages.verify.citation_metadata import MetadataMatch
from evalit_4me.stages.verify.confidence import aggregate_verification
from evalit_4me.stages.verify.temporal import TemporalIssue


def _claim(
    cid: str,
    *,
    refs: list[str],
    claim_type: ClaimType = ClaimType.CITATION,
    severity: Severity = Severity.HIGH,
) -> Claim:
    return Claim(
        id=cid,
        text="x",
        claim_type=claim_type,
        severity=severity,
        source_span=SourceSpan(section_id="s", char_start=0, char_end=1),
        referenced_citation_ids=refs,
    )


def _found(rid: str, source=VerificationSource.CROSSREF) -> CitationLookup:
    return CitationLookup(
        reference_id=rid,
        status=LookupStatus.FOUND,
        source=source,
        metadata=ExternalMetadata(title="T", year=2020),
    )


def _missing(rid: str) -> CitationLookup:
    return CitationLookup(
        reference_id=rid, status=LookupStatus.NOT_FOUND, source=VerificationSource.NONE
    )


def _good_match() -> MetadataMatch:
    return MetadataMatch(
        author_score=1.0,
        year_score=1.0,
        title_score=1.0,
        venue_score=1.0,
        overall=1.0,
        match_ok=True,
    )


def _bad_match() -> MetadataMatch:
    return MetadataMatch(
        author_score=0.1,
        year_score=0.0,
        title_score=0.0,
        venue_score=0.0,
        overall=0.1,
        match_ok=False,
        mismatches=("title",),
    )


def test_claim_with_resolved_citation_is_verified():
    claim = _claim("c1", refs=["r1"])
    ledger = aggregate_verification(
        claims=[claim],
        lookups=[_found("r1")],
        matches={"r1": _good_match()},
        temporal=[],
    )
    assert ledger.total_claims == 1
    assert ledger.verified_count == 1
    assert ledger.hallucination_count == 0
    assert ledger.results[0].verified is True
    assert ledger.results[0].confidence >= 0.9
    assert ledger.results[0].source == VerificationSource.CROSSREF


def test_claim_with_missing_citation_flags_hallucination():
    claim = _claim("c1", refs=["r1"])
    ledger = aggregate_verification(
        claims=[claim],
        lookups=[_missing("r1")],
        matches={},
        temporal=[],
    )
    assert ledger.hallucination_count == 1
    assert ledger.results[0].verified is False
    assert ledger.results[0].hallucination_flag is True


def test_fabrication_catch_10_fakes():
    """Exit gate: 10 claims each referencing a fabricated citation all flag."""
    claims = [_claim(f"c{i}", refs=[f"fake-{i}"]) for i in range(10)]
    lookups = [_missing(f"fake-{i}") for i in range(10)]
    ledger = aggregate_verification(claims=claims, lookups=lookups, matches={}, temporal=[])
    assert ledger.hallucination_count == 10
    assert all(r.hallucination_flag for r in ledger.results)


def test_zero_false_positives_on_10_real():
    """Exit gate: 10 claims, each with a real+matching citation -> all verified."""
    claims = [_claim(f"c{i}", refs=[f"real-{i}"]) for i in range(10)]
    lookups = [_found(f"real-{i}") for i in range(10)]
    matches = {f"real-{i}": _good_match() for i in range(10)}
    ledger = aggregate_verification(claims=claims, lookups=lookups, matches=matches, temporal=[])
    assert ledger.hallucination_count == 0
    assert ledger.verified_count == 10


def test_low_metadata_match_lowers_confidence():
    claim = _claim("c", refs=["r"])
    ledger = aggregate_verification(
        claims=[claim],
        lookups=[_found("r")],
        matches={"r": _bad_match()},
        temporal=[],
    )
    # Bad match => confidence < 0.6 => verified=False.
    assert ledger.results[0].verified is False
    assert ledger.results[0].confidence < 0.6


def test_temporal_issue_overrides_match():
    claim = _claim("c", refs=["r"])
    ledger = aggregate_verification(
        claims=[claim],
        lookups=[_found("r")],
        matches={"r": _good_match()},
        temporal=[
            TemporalIssue(reference_id="r", reason="future", reference_year=2099, paper_year=2020)
        ],
    )
    assert ledger.results[0].verified is False
    assert ledger.results[0].hallucination_flag is True
    assert ledger.results[0].confidence <= 0.3


def test_claim_without_refs_not_flagged():
    claim = _claim("c", refs=[], claim_type=ClaimType.EMPIRICAL, severity=Severity.MEDIUM)
    ledger = aggregate_verification(claims=[claim], lookups=[], matches={}, temporal=[])
    assert ledger.results[0].hallucination_flag is False
    assert ledger.results[0].verified is False
    assert ledger.results[0].confidence == 0.0


def test_categorized_citation_without_refs_has_note():
    """A claim marked CITATION but with empty ref list is surfaced as a
    possible extraction bug via `notes`."""
    claim = _claim("c", refs=[])
    ledger = aggregate_verification(claims=[claim], lookups=[], matches={}, temporal=[])
    assert ledger.results[0].notes is not None
    assert "no referenced" in ledger.results[0].notes.lower()


def test_mean_confidence_is_correct():
    claims = [
        _claim("c1", refs=["r1"]),
        _claim("c2", refs=["r2"]),
    ]
    lookups = [_found("r1"), _missing("r2")]
    matches = {"r1": _good_match()}
    ledger = aggregate_verification(claims=claims, lookups=lookups, matches=matches, temporal=[])
    # One at 1.0, one at 0.0 -> mean 0.5.
    assert abs(ledger.mean_confidence - 0.5) < 1e-6
