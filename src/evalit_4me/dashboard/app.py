"""Streamlit reviewer view — single-page app.

Layout (top to bottom):
    1. Score card (recommendation + overall score + reviewer confidence)
    2. Compliance summary
    3. Flagged citations with evidence
    4. Depth scores (4 bars + rationales)
    5. Rubric scores (per-dimension score + rationale)
    6. Copy-paste review draft block (markdown)

Each section is returned as a `ViewSection(title, body_markdown)` so the
content is test-accessible without requiring Streamlit in CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from evalit_4me.contracts import EvaluationRecord
from evalit_4me.formatters.reviewer import format_review_draft, render_review_markdown


@dataclass(frozen=True)
class ViewSection:
    title: str
    body_markdown: str


def build_view_sections(record: EvaluationRecord) -> list[ViewSection]:
    """Pure function: produces the structured content the Streamlit UI renders.

    Exercised directly by the smoke test — Streamlit is not required.
    """
    draft = format_review_draft(record)
    sections: list[ViewSection] = [
        ViewSection(
            title="Score card",
            body_markdown=_score_card(record, draft),
        ),
        ViewSection(
            title="Composite breakdown",
            body_markdown=_composite_section(draft),
        ),
        ViewSection(
            title="Compliance",
            body_markdown=_compliance_section(record),
        ),
        ViewSection(
            title="Flagged citations",
            body_markdown=_flagged_citations_section(record),
        ),
        ViewSection(
            title="Depth scores",
            body_markdown=_depth_section(record),
        ),
        ViewSection(
            title="Rubric scores",
            body_markdown=_rubric_section(record),
        ),
        ViewSection(
            title="Review draft (copy-paste)",
            body_markdown="```markdown\n" + render_review_markdown(draft) + "```\n",
        ),
    ]
    return sections


def run_app(record_path: Path | str | None = None) -> None:  # pragma: no cover — UI driver
    """Streamlit entrypoint. Loads a record from JSON, renders sections."""
    import json

    import streamlit as st  # type: ignore[import-not-found]

    st.set_page_config(page_title="evalit-4me", layout="wide")
    st.title("evalit-4me — reviewer view")

    path = Path(record_path) if record_path else None
    if path is None:
        uploaded = st.file_uploader("Upload an EvaluationRecord JSON", type=["json"])
        if uploaded is None:
            st.info("Run `evalit review <paper.pdf> --output record.json` and upload the file.")
            return
        data = json.loads(uploaded.read())
    else:
        data = json.loads(path.read_text(encoding="utf-8"))

    record = EvaluationRecord.model_validate(data)
    for section in build_view_sections(record):
        st.header(section.title)
        st.markdown(section.body_markdown, unsafe_allow_html=False)
        st.divider()


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _score_card(record: EvaluationRecord, draft) -> str:
    banner = f"\n\n> {draft.compliance_warning}\n" if draft.compliance_warning else ""
    return (
        f"- **Paper**: {record.paper.metadata.title}\n"
        f"- **Recommendation**: **{draft.recommendation.value}**\n"
        f"- **Composite score** (0..1): {draft.overall_score:.2f}\n"
        f"- **Reviewer confidence** (0..1): {draft.reviewer_confidence:.2f}\n"
        f"- **Hallucination flags**: {record.claims.hallucination_count} "
        f"/ {record.claims.total_claims} claims"
        f"{banner}"
    )


def _composite_section(draft) -> str:
    if not draft.composite_breakdown:
        return "_Composite breakdown not available._"
    lines = ["| Stage | Subscore |", "|---|---|"]
    for name, val in draft.composite_breakdown.items():
        display = f"{val:.2f}" if val is not None else "_skipped_"
        lines.append(f"| {name} | {display} |")
    lines.append("")
    lines.append(f"**Composite (weighted): {draft.overall_score:.3f}**")
    return "\n".join(lines)


def _compliance_section(record: EvaluationRecord) -> str:
    comp = record.compliance
    lines = [f"**Triage**: {comp.triage.value}"]
    if comp.issues:
        lines.append("\n**Issues:**")
        lines.extend(f"- {issue}" for issue in comp.issues)
    lines.append("\n**Section checks:**")
    for c in comp.section_checks:
        marker = "✓" if c.passed else "✗"
        detail = f" — {c.detail}" if c.detail else ""
        lines.append(f"- {marker} {c.name}{detail}")
    if comp.format_checks:
        lines.append("\n**Format checks:**")
        for c in comp.format_checks:
            marker = "✓" if c.passed else "✗"
            detail = f" — {c.detail}" if c.detail else ""
            lines.append(f"- {marker} {c.name}{detail}")
    return "\n".join(lines)


def _flagged_citations_section(record: EvaluationRecord) -> str:
    flagged = [
        (c, r)
        for c, r in zip(record.claims.claims, record.claims.results, strict=False)
        if r.hallucination_flag
    ]
    if not flagged:
        return "_No flagged citations._"
    lines: list[str] = []
    for claim, result in flagged:
        lines.append(f"### Claim `{claim.id}` — severity {claim.severity.value}")
        lines.append(f"> {claim.text}")
        if claim.referenced_citation_ids:
            lines.append(f"- **Cited refs**: {', '.join(claim.referenced_citation_ids)}")
        if result.evidence:
            lines.append(f"- **Evidence**: {result.evidence}")
        if result.notes:
            lines.append(f"- **Notes**: {result.notes}")
        lines.append("")
    return "\n".join(lines)


def _depth_section(record: EvaluationRecord) -> str:
    if record.depth is None:
        return "_Depth analysis not run._"
    d = record.depth
    lines = [
        "| Dimension | Score | Rationale |",
        "|---|---|---|",
        _depth_row("Methodology", d.methodology_score, d.rationales.get("methodology", "")),
        _depth_row("Limitations", d.limitations_score, d.rationales.get("limitations", "")),
        _depth_row(
            "Reproducibility", d.reproducibility_score, d.rationales.get("reproducibility", "")
        ),
        _depth_row(
            "Logical soundness",
            d.logical_soundness_score,
            d.rationales.get("logical_soundness", ""),
        ),
    ]
    return "\n".join(lines)


def _depth_row(name: str, score: float, rationale: str) -> str:
    return f"| {name} | {score:.2f} | {rationale or '—'} |"


def _rubric_section(record: EvaluationRecord) -> str:
    if record.rubric is None:
        return "_Rubric not computed._"
    r = record.rubric
    lines = [
        f"**Rubric**: `{r.rubric_id}`",
        f"- Raw total (0..1): {r.raw_total:.3f}",
        f"- Bias-adjusted total (0..1): {r.bias_adjusted_total:.3f}",
    ]
    if r.adjustment_notes:
        for note in r.adjustment_notes:
            lines.append(f"- {note}")
    lines.append("")
    lines.append("| Dimension | Score | Max | Rationale |")
    lines.append("|---|---|---|---|")
    for d in r.dimensions:
        lines.append(f"| {d.name} | {d.score:.2f} | {d.max_score} | {d.rationale or '—'} |")
    return "\n".join(lines)
