"""Shared Pydantic contracts.

Every pipeline stage reads and writes one or more of these models. They form
the interface backbone of the system; later chunks must not silently extend
them — `extra="forbid"` enforces this.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, validate_assignment=True)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ClaimType(StrEnum):
    CITATION = "CITATION"
    STATISTICAL = "STATISTICAL"
    CAPABILITY = "CAPABILITY"
    EMPIRICAL = "EMPIRICAL"
    TEMPORAL = "TEMPORAL"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class VerificationSource(StrEnum):
    CROSSREF = "crossref"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    OPENALEX = "openalex"
    ORCID = "orcid"
    LLM = "llm"
    HEURISTIC = "heuristic"
    NONE = "none"


class Triage(StrEnum):
    """Compliance triage outcome — a sort signal for a human reviewer, not a gate.

    - ``PASS``: no compliance red flags; reviewer can focus on substance.
    - ``CONDITIONAL``: minor issues (formatting, word count, anonymization
      uncertainty); a reviewer should confirm before making a decision.
    - ``FAIL``: serious compliance concerns (missing sections, no ethics
      statement, obvious anonymization breaks); a reviewer should examine
      first. **Never auto-reject.**

    The composite score owns the final recommendation; compliance only
    surfaces an advisory banner above the summary.
    """

    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class Recommendation(StrEnum):
    STRONG_ACCEPT = "STRONG_ACCEPT"
    ACCEPT = "ACCEPT"
    WEAK_ACCEPT = "WEAK_ACCEPT"
    BORDERLINE = "BORDERLINE"
    WEAK_REJECT = "WEAK_REJECT"
    REJECT = "REJECT"
    STRONG_REJECT = "STRONG_REJECT"


# ---------------------------------------------------------------------------
# Paper (output of ingest stage)
# ---------------------------------------------------------------------------


class SourceSpan(_Strict):
    """Pointer back into a Paper for traceability."""

    section_id: str
    char_start: NonNegativeInt
    char_end: NonNegativeInt

    @model_validator(mode="after")
    def _check_range(self) -> SourceSpan:
        if self.char_end < self.char_start:
            raise ValueError("char_end must be >= char_start")
        return self


class Section(_Strict):
    id: str
    title: str
    text: str
    order: NonNegativeInt


class Reference(_Strict):
    id: str
    raw: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    url: str | None = None


class Figure(_Strict):
    id: str
    caption: str | None = None
    page: NonNegativeInt | None = None


class Table(_Strict):
    id: str
    caption: str | None = None
    page: NonNegativeInt | None = None


class PaperMetadata(_Strict):
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    arxiv_id: str | None = None
    openreview_id: str | None = None
    doi: str | None = None
    venue: str | None = None
    year: int | None = None


class Paper(_Strict):
    """Normalized output of the ingest stage."""

    id: str
    metadata: PaperMetadata
    sections: list[Section] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Claims + verification (Stage 2)
# ---------------------------------------------------------------------------


class Claim(_Strict):
    id: str
    text: str
    claim_type: ClaimType
    severity: Severity
    source_span: SourceSpan
    referenced_citation_ids: list[str] = Field(default_factory=list)


class VerificationResult(_Strict):
    """Per-claim verification outcome."""

    claim_id: str
    verified: bool
    confidence: float = Field(ge=0.0, le=1.0)
    source: VerificationSource
    evidence: str | None = None
    hallucination_flag: bool = False
    notes: str | None = None


class ClaimLedger(_Strict):
    """Aggregate of all verification results for a paper."""

    claims: list[Claim] = Field(default_factory=list)
    results: list[VerificationResult] = Field(default_factory=list)
    total_claims: NonNegativeInt = 0
    verified_count: NonNegativeInt = 0
    hallucination_count: NonNegativeInt = 0
    mean_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Compliance (Stage 1)
# ---------------------------------------------------------------------------


class ComplianceCheck(_Strict):
    name: str
    passed: bool
    detail: str | None = None


class ComplianceReport(_Strict):
    triage: Triage
    section_checks: list[ComplianceCheck] = Field(default_factory=list)
    format_checks: list[ComplianceCheck] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Depth (Stage 3)
# ---------------------------------------------------------------------------


class DepthReport(_Strict):
    methodology_score: float = Field(ge=0.0, le=1.0)
    limitations_score: float = Field(ge=0.0, le=1.0)
    reproducibility_score: float = Field(ge=0.0, le=1.0)
    logical_soundness_score: float = Field(ge=0.0, le=1.0)
    rationales: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Rubric (Stage 4)
# ---------------------------------------------------------------------------


class DimensionScore(_Strict):
    name: str
    score: float
    max_score: float = Field(gt=0.0)
    rationale: str | None = None

    @model_validator(mode="after")
    def _check_score(self) -> DimensionScore:
        if not 0.0 <= self.score <= self.max_score:
            raise ValueError(
                f"score {self.score} must be in [0, {self.max_score}] for {self.name!r}"
            )
        return self


class RubricScores(_Strict):
    rubric_id: str
    dimensions: list[DimensionScore] = Field(default_factory=list)
    raw_total: float
    bias_adjusted_total: float
    adjustment_notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level evaluation record + reviewer-facing draft
# ---------------------------------------------------------------------------


class Provenance(_Strict):
    """Reproducibility footprint for a single evaluation run."""

    evalit_version: str
    config_hash: str
    llm_models: dict[str, str] = Field(default_factory=dict)
    seeds: dict[str, int] = Field(default_factory=dict)
    cost_usd: float = Field(default=0.0, ge=0.0)


class EvaluationRecord(_Strict):
    """Top-level record persisted to the audit log."""

    paper: Paper
    compliance: ComplianceReport
    claims: ClaimLedger
    depth: DepthReport | None = None
    rubric: RubricScores | None = None
    provenance: Provenance
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = Field(default_factory=dict)


class ReviewDraft(_Strict):
    """Reviewer-facing markdown payload.

    `overall_score` is the composite 5-stage weighted score in [0, 1]
    (see `stages/scoring.py`). `composite_breakdown` carries the
    per-stage subscore values for display; keys are the same as
    `evalit_4me.config.SCORING_KEYS`, values are either a float in
    [0, 1] or `None` when the stage was skipped.

    `compliance_warning` is a human-readable banner that appears above
    the summary when compliance triage is not PASS. Compliance issues
    never force the recommendation by themselves — the banner surfaces
    the concern but the score-based threshold owns the decision.
    """

    paper_id: str
    summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    overall_score: float
    reviewer_confidence: float = Field(ge=0.0, le=1.0)
    recommendation: Recommendation
    flagged_citations: list[str] = Field(default_factory=list)
    composite_breakdown: dict[str, float | None] = Field(default_factory=dict)
    compliance_warning: str | None = None
