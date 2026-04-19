"""Round-trip and invalid-shape tests for contracts.

These are the load-bearing invariants every downstream stage depends on:
  1. Every model survives `model_dump() -> model_validate()` losslessly.
  2. Extra/unknown fields are rejected (so stages can't silently drift).
  3. Declared ranges (scores, spans, probabilities) are enforced.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from evalit_4me.contracts import (
    Claim,
    ClaimLedger,
    ClaimType,
    ComplianceCheck,
    ComplianceReport,
    DepthReport,
    DimensionScore,
    EvaluationRecord,
    Figure,
    Paper,
    PaperMetadata,
    Provenance,
    Recommendation,
    Reference,
    ReviewDraft,
    RubricScores,
    Section,
    Severity,
    SourceSpan,
    Table,
    Triage,
    VerificationResult,
    VerificationSource,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _paper() -> Paper:
    return Paper(
        id="arxiv:2401.00001",
        metadata=PaperMetadata(
            title="A Tiny Paper",
            authors=["Ada Lovelace"],
            abstract="We propose something.",
            arxiv_id="2401.00001",
            year=2024,
        ),
        sections=[
            Section(id="s1", title="Introduction", text="Hello.", order=0),
            Section(id="s2", title="Method", text="We do X.", order=1),
        ],
        references=[
            Reference(id="r1", raw="Lovelace 1843", title="Notes", year=1843),
        ],
        figures=[Figure(id="f1", caption="overview", page=2)],
        tables=[Table(id="t1", caption="results", page=4)],
    )


def _span() -> SourceSpan:
    return SourceSpan(section_id="s2", char_start=0, char_end=8)


def _claim() -> Claim:
    return Claim(
        id="c1",
        text="We do X.",
        claim_type=ClaimType.CAPABILITY,
        severity=Severity.MEDIUM,
        source_span=_span(),
        referenced_citation_ids=["r1"],
    )


def _verification() -> VerificationResult:
    return VerificationResult(
        claim_id="c1",
        verified=True,
        confidence=0.92,
        source=VerificationSource.SEMANTIC_SCHOLAR,
        evidence="Found in abstract.",
    )


def _ledger() -> ClaimLedger:
    return ClaimLedger(
        claims=[_claim()],
        results=[_verification()],
        total_claims=1,
        verified_count=1,
        hallucination_count=0,
        mean_confidence=0.92,
    )


def _compliance() -> ComplianceReport:
    return ComplianceReport(
        triage=Triage.PASS,
        section_checks=[ComplianceCheck(name="abstract_present", passed=True)],
        format_checks=[ComplianceCheck(name="word_count", passed=True, detail="7500")],
    )


def _depth() -> DepthReport:
    return DepthReport(
        methodology_score=0.8,
        limitations_score=0.6,
        reproducibility_score=0.7,
        logical_soundness_score=0.75,
        rationales={"methodology": "clear ablations"},
    )


def _rubric() -> RubricScores:
    return RubricScores(
        rubric_id="neurips-2024",
        dimensions=[
            DimensionScore(name="novelty", score=7.5, max_score=10.0, rationale="new idea"),
            DimensionScore(name="clarity", score=6.0, max_score=10.0),
        ],
        raw_total=13.5,
        bias_adjusted_total=13.2,
        adjustment_notes=["length normalization -0.3"],
    )


def _provenance() -> Provenance:
    return Provenance(
        evalit_version="0.0.1",
        config_hash="deadbeef",
        llm_models={"claim_decomp": "claude-sonnet-4-6"},
        seeds={"claim_decomp": 0},
        cost_usd=0.04,
    )


def _record() -> EvaluationRecord:
    return EvaluationRecord(
        paper=_paper(),
        compliance=_compliance(),
        claims=_ledger(),
        depth=_depth(),
        rubric=_rubric(),
        provenance=_provenance(),
    )


def _draft() -> ReviewDraft:
    return ReviewDraft(
        paper_id="arxiv:2401.00001",
        summary="Tiny paper proposing X.",
        strengths=["clear"],
        weaknesses=["no baselines"],
        questions=["how does X compare to Y?"],
        overall_score=6.0,
        reviewer_confidence=0.8,
        recommendation=Recommendation.WEAK_ACCEPT,
        flagged_citations=[],
    )


ALL_FIXTURES = [
    _paper,
    _span,
    _claim,
    _verification,
    _ledger,
    _compliance,
    _depth,
    _rubric,
    _provenance,
    _record,
    _draft,
]


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", ALL_FIXTURES, ids=lambda f: f.__name__)
def test_round_trip_json(factory):
    instance = factory()
    dumped = instance.model_dump_json()
    rebuilt = type(instance).model_validate_json(dumped)
    assert rebuilt == instance


@pytest.mark.parametrize("factory", ALL_FIXTURES, ids=lambda f: f.__name__)
def test_round_trip_dict(factory):
    instance = factory()
    rebuilt = type(instance).model_validate(instance.model_dump())
    assert rebuilt == instance


# ---------------------------------------------------------------------------
# Extra-field rejection (catches silent drift)
# ---------------------------------------------------------------------------


def test_extra_field_rejected_on_paper():
    payload = _paper().model_dump()
    payload["secret_field"] = "oops"
    with pytest.raises(ValidationError):
        Paper.model_validate(payload)


def test_extra_field_rejected_on_review_draft():
    payload = _draft().model_dump()
    payload["score"] = 9  # wrong field name; real field is `overall_score`
    with pytest.raises(ValidationError):
        ReviewDraft.model_validate(payload)


# ---------------------------------------------------------------------------
# Range / invariant checks
# ---------------------------------------------------------------------------


def test_source_span_rejects_inverted_range():
    with pytest.raises(ValidationError):
        SourceSpan(section_id="s1", char_start=10, char_end=5)


def test_confidence_bounds_enforced():
    with pytest.raises(ValidationError):
        VerificationResult(
            claim_id="c1",
            verified=True,
            confidence=1.5,
            source=VerificationSource.LLM,
        )


def test_depth_scores_bounded():
    with pytest.raises(ValidationError):
        DepthReport(
            methodology_score=1.1,
            limitations_score=0.5,
            reproducibility_score=0.5,
            logical_soundness_score=0.5,
        )


def test_dimension_score_cannot_exceed_max():
    with pytest.raises(ValidationError):
        DimensionScore(name="novelty", score=11.0, max_score=10.0)


def test_reviewer_confidence_bounded():
    with pytest.raises(ValidationError):
        ReviewDraft(
            paper_id="p1",
            summary="x",
            overall_score=5.0,
            reviewer_confidence=2.0,
            recommendation=Recommendation.ACCEPT,
        )


def test_enum_rejects_unknown_value():
    with pytest.raises(ValidationError):
        Claim(
            id="c1",
            text="t",
            claim_type="NOT_A_TYPE",  # type: ignore[arg-type]
            severity=Severity.LOW,
            source_span=_span(),
        )


def test_evaluation_record_created_at_is_utc():
    record = _record()
    assert record.created_at.tzinfo is not None
