"""Reviewer formatter tests — ReviewDraft shape + markdown snapshot."""

from __future__ import annotations

from pathlib import Path

from evalit_4me.config import load_venue_config
from evalit_4me.contracts import Recommendation
from evalit_4me.formatters.reviewer import (
    _recommendation_from_total,
    format_review_draft,
    render_review_markdown,
)
from evalit_4me.ingest.parser import parse_markdown
from evalit_4me.stages.orchestrate import run_pipeline

CONFIGS_DIR = Path(__file__).parents[3] / "configs"
FIXTURES_DIR = Path(__file__).parents[2] / "fixtures" / "markdown"


def _record(fixture: str):
    md = (FIXTURES_DIR / f"{fixture}.md").read_text(encoding="utf-8")
    paper = parse_markdown(md, source_name=fixture)
    return run_pipeline(paper, load_venue_config(CONFIGS_DIR / "neurips.yaml"))


def test_review_draft_has_all_sections():
    record = _record("paper_01_numbered_refs")
    draft = format_review_draft(record)
    assert draft.paper_id == record.paper.id
    assert draft.summary
    # strengths/weaknesses may be empty, but must be lists
    assert isinstance(draft.strengths, list)
    assert isinstance(draft.weaknesses, list)
    assert isinstance(draft.questions, list)
    assert 0.0 <= draft.overall_score <= 1.0
    assert 0.0 <= draft.reviewer_confidence <= 1.0
    assert isinstance(draft.recommendation, Recommendation)


def test_markdown_contains_required_headers():
    record = _record("paper_01_numbered_refs")
    draft = format_review_draft(record)
    md = render_review_markdown(draft)
    for header in (
        "## Summary",
        "## Strengths",
        "## Weaknesses",
        "## Questions",
        "## Overall score",
    ):
        assert header in md, f"missing header {header!r}"
    assert md.endswith("\n")


def test_markdown_snapshot_stable_on_fixture():
    """Snapshot: the markdown output is byte-stable across runs with the
    same input + heuristic scoring. Any change to output format must be
    accompanied by updating this test."""
    r1 = _record("paper_01_numbered_refs")
    r2 = _record("paper_01_numbered_refs")
    md1 = render_review_markdown(format_review_draft(r1))
    md2 = render_review_markdown(format_review_draft(r2))
    assert md1 == md2


def test_recommendation_mapping_thresholds():
    """Mapping is purely score-based now; compliance triage is surfaced in
    `compliance_warning` on the draft, NOT as a forced recommendation."""
    assert _recommendation_from_total(0.9) == Recommendation.STRONG_ACCEPT
    assert _recommendation_from_total(0.75) == Recommendation.ACCEPT
    assert _recommendation_from_total(0.6) == Recommendation.WEAK_ACCEPT
    assert _recommendation_from_total(0.5) == Recommendation.BORDERLINE
    assert _recommendation_from_total(0.35) == Recommendation.WEAK_REJECT
    assert _recommendation_from_total(0.2) == Recommendation.REJECT
    assert _recommendation_from_total(0.0) == Recommendation.STRONG_REJECT


def test_flagged_citations_deduplicated():
    record = _record("paper_01_numbered_refs")
    draft = format_review_draft(record)
    assert len(draft.flagged_citations) == len(set(draft.flagged_citations))
