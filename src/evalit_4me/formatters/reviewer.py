"""Reviewer formatter: `EvaluationRecord` -> `ReviewDraft` + markdown.

Two steps on purpose:

1. `format_review_draft(record)` builds the contract-typed `ReviewDraft`
   (summary, strengths, weaknesses, questions, score, recommendation).
   This is the thing we persist + snapshot-test.
2. `render_review_markdown(draft)` produces a venue-style markdown block
   the reviewer pastes into OpenReview.

Keeping them separate means test snapshots lock down the *structured*
output — if we later change the markdown skin, the contract-level tests
don't break.
"""

from __future__ import annotations

from evalit_4me.config import ScoringConfig, VenueConfig
from evalit_4me.contracts import (
    ClaimType,
    EvaluationRecord,
    Recommendation,
    ReviewDraft,
    Severity,
    Triage,
)
from evalit_4me.stages.scoring import composite_score


def format_review_draft(
    record: EvaluationRecord,
    *,
    config: VenueConfig | ScoringConfig | None = None,
) -> ReviewDraft:
    """Build a `ReviewDraft` from an `EvaluationRecord`.

    The optional `config` argument carries scoring weights; omit it to use
    the shipped defaults. Passing a `VenueConfig` reuses the config's
    `scoring` block so the draft reflects the same weights the pipeline
    was configured with.
    """
    cs = composite_score(record, config)
    summary = _build_summary(record)
    strengths = _build_strengths(record)
    weaknesses = _build_weaknesses(record)
    questions = _build_questions(record)
    reviewer_confidence = _reviewer_confidence(record)
    flagged = _flagged_citation_ids(record)
    recommendation = _recommendation_from_total(cs.composite)
    return ReviewDraft(
        paper_id=record.paper.id,
        summary=summary,
        strengths=strengths,
        weaknesses=weaknesses,
        questions=questions,
        overall_score=round(cs.composite, 4),
        reviewer_confidence=reviewer_confidence,
        recommendation=recommendation,
        flagged_citations=flagged,
        composite_breakdown=cs.breakdown(),
        compliance_warning=cs.warning_banner,
    )


def render_review_markdown(draft: ReviewDraft) -> str:
    lines: list[str] = []
    if draft.compliance_warning:
        lines.append(f"> {draft.compliance_warning}")
        lines.append("")
    lines.append("## Summary")
    lines.append(draft.summary or "_No summary generated._")
    lines.append("")
    if draft.composite_breakdown:
        lines.append("## Composite breakdown")
        lines.append("| Stage | Subscore |")
        lines.append("|---|---|")
        for name, val in draft.composite_breakdown.items():
            display = f"{val:.2f}" if val is not None else "_skipped_"
            lines.append(f"| {name} | {display} |")
        lines.append("")
    lines.append("## Strengths")
    if draft.strengths:
        lines.extend(f"- {s}" for s in draft.strengths)
    else:
        lines.append("- _None identified._")
    lines.append("")
    lines.append("## Weaknesses")
    if draft.weaknesses:
        lines.extend(f"- {w}" for w in draft.weaknesses)
    else:
        lines.append("- _None identified._")
    lines.append("")
    lines.append("## Questions for the authors")
    if draft.questions:
        lines.extend(f"- {q}" for q in draft.questions)
    else:
        lines.append("- _No questions._")
    lines.append("")
    lines.append("## Overall score")
    lines.append(
        f"- Score: **{draft.overall_score:.2f}** (0..1 scale)\n"
        f"- Reviewer confidence: {draft.reviewer_confidence:.2f}\n"
        f"- Recommendation: **{draft.recommendation.value}**"
    )
    if draft.flagged_citations:
        lines.append("")
        lines.append("## Flagged citations")
        lines.extend(f"- {rid}" for rid in draft.flagged_citations)
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_summary(record: EvaluationRecord) -> str:
    title = record.paper.metadata.title or "(untitled)"
    abstract = (record.paper.metadata.abstract or "").strip()
    if not abstract:
        return f"{title}. Abstract not available."
    short_abstract = abstract if len(abstract) < 600 else abstract[:600].rsplit(" ", 1)[0] + "..."
    return f"{title}. {short_abstract}"


def _build_strengths(record: EvaluationRecord) -> list[str]:
    out: list[str] = []
    if record.rubric is not None:
        sorted_dims = sorted(
            record.rubric.dimensions,
            key=lambda d: d.score / d.max_score,
            reverse=True,
        )
        top = sorted_dims[:2]
        for dim in top:
            if dim.score / dim.max_score >= 0.6:
                out.append(
                    f"Strong {dim.name}: {dim.score:.2f}/{dim.max_score}"
                    + (f" — {dim.rationale}" if dim.rationale else "")
                )
    if record.depth is not None and record.depth.reproducibility_score >= 0.75:
        out.append(
            "Reproducibility signals are strong (code/data/hyperparameter references present)."
        )
    if record.compliance.triage == Triage.PASS:
        out.append("All compliance checks pass (sections, references, ethics).")
    return out


def _build_weaknesses(record: EvaluationRecord) -> list[str]:
    out: list[str] = []
    for issue in record.compliance.issues:
        out.append(f"Compliance: {issue}")
    # Hallucinated or unsupported citations.
    flagged = [r for r in record.claims.results if r.hallucination_flag]
    if flagged:
        out.append(
            f"{len(flagged)} claim(s) reference citations that could not be verified "
            f"or were found to contradict the cited abstract."
        )
    if record.rubric is not None:
        weakest = min(record.rubric.dimensions, key=lambda d: d.score / d.max_score, default=None)
        if weakest is not None and weakest.score / weakest.max_score < 0.4:
            out.append(
                f"Weak {weakest.name}: {weakest.score:.2f}/{weakest.max_score}"
                + (f" — {weakest.rationale}" if weakest.rationale else "")
            )
    if record.depth is not None and record.depth.limitations_score < 0.3:
        out.append("Limitations / broader-impact discussion is thin or missing.")
    return out


def _build_questions(record: EvaluationRecord) -> list[str]:
    out: list[str] = []
    # Ask about each CRITICAL-severity unverified claim.
    critical = [
        c
        for c, r in zip(record.claims.claims, record.claims.results, strict=False)
        if c.severity == Severity.CRITICAL and not r.verified
    ]
    for c in critical[:3]:
        out.append(
            f'Claim {c.id}: can the authors point to concrete evidence supporting "{c.text}"?'
        )
    # Ask about top STATISTICAL claims when no verification signal exists.
    stats_unverified = [
        c
        for c, r in zip(record.claims.claims, record.claims.results, strict=False)
        if c.claim_type == ClaimType.STATISTICAL and r.confidence < 0.3
    ]
    for c in stats_unverified[:2]:
        out.append(f'How was "{c.text}" measured? (confidence interval / variance over runs?)')
    return out


def _reviewer_confidence(record: EvaluationRecord) -> float:
    """A meta-confidence that this synthetic review is trustworthy enough
    to defer to without cross-reading the paper.

    Composed from: verification coverage, depth completeness, compliance status.
    """
    ledger = record.claims
    coverage = (
        (ledger.verified_count + ledger.hallucination_count) / ledger.total_claims
        if ledger.total_claims
        else 0.0
    )
    depth_confidence = 0.0
    if record.depth is not None:
        depth_confidence = (
            record.depth.methodology_score
            + record.depth.limitations_score
            + record.depth.reproducibility_score
            + record.depth.logical_soundness_score
        ) / 4.0
    compliance_ok = 1.0 if record.compliance.triage == Triage.PASS else 0.5
    confidence = 0.35 * coverage + 0.35 * depth_confidence + 0.30 * compliance_ok
    return round(max(0.0, min(1.0, confidence)), 4)


def _flagged_citation_ids(record: EvaluationRecord) -> list[str]:
    return sorted(
        {
            rid
            for c, r in zip(record.claims.claims, record.claims.results, strict=False)
            for rid in c.referenced_citation_ids
            if r.hallucination_flag
        }
    )


# ---------------------------------------------------------------------------
# Recommendation mapping
# ---------------------------------------------------------------------------


_THRESHOLDS = (
    (0.85, Recommendation.STRONG_ACCEPT),
    (0.70, Recommendation.ACCEPT),
    (0.55, Recommendation.WEAK_ACCEPT),
    (0.45, Recommendation.BORDERLINE),
    (0.30, Recommendation.WEAK_REJECT),
    (0.15, Recommendation.REJECT),
)


def _recommendation_from_total(total: float) -> Recommendation:
    """Map a normalized [0, 1] composite score to a recommendation label.

    Compliance issues no longer force the recommendation — the composite
    already weights compliance proportionally, and the `ReviewDraft`
    carries a warning banner. Dropping the hard override was the direct
    response to Shumailov "Curse of Recursion" scoring 0.77 on rubric but
    being forced to STRONG_REJECT because marker missed one section
    header (see `.reports/2026-04-18-venue-config-comparison.md`).
    """
    for threshold, rec in _THRESHOLDS:
        if total >= threshold:
            return rec
    return Recommendation.STRONG_REJECT
