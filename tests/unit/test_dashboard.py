"""Streamlit app smoke tests — exercises the pure section builder.

Streamlit itself is NOT a test dependency (it's in the `[dashboard]`
extra). The smoke test asserts the structured content generation works
for a real fixture record without ever importing Streamlit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalit_4me.config import load_venue_config
from evalit_4me.dashboard import ViewSection, build_view_sections
from evalit_4me.ingest.parser import parse_markdown
from evalit_4me.stages.orchestrate import run_pipeline

CONFIGS_DIR = Path(__file__).parents[2] / "configs"
FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "markdown"


@pytest.fixture(scope="module")
def record():
    md = (FIXTURES_DIR / "paper_01_numbered_refs.md").read_text(encoding="utf-8")
    paper = parse_markdown(md, source_name="paper_01")
    return run_pipeline(paper, load_venue_config(CONFIGS_DIR / "neurips.yaml"))


EXPECTED_TITLES = [
    "Score card",
    "Composite breakdown",
    "Compliance",
    "Flagged citations",
    "Depth scores",
    "Rubric scores",
    "Review draft (copy-paste)",
]


def _section(sections: list[ViewSection], title: str) -> ViewSection:
    for s in sections:
        if s.title == title:
            return s
    raise KeyError(title)


def test_build_view_sections_produces_seven_sections(record):
    sections = build_view_sections(record)
    assert [s.title for s in sections] == EXPECTED_TITLES
    for s in sections:
        assert isinstance(s, ViewSection)
        assert s.body_markdown.strip()


def test_score_card_contains_recommendation(record):
    score_card = _section(build_view_sections(record), "Score card").body_markdown
    assert "Recommendation" in score_card
    assert "Hallucination flags" in score_card
    assert "Composite score" in score_card


def test_composite_section_lists_all_four_stages(record):
    md = _section(build_view_sections(record), "Composite breakdown").body_markdown
    for stage in ("compliance", "verification", "depth", "rubric"):
        assert stage in md


def test_rubric_section_lists_all_dimensions(record):
    md = _section(build_view_sections(record), "Rubric scores").body_markdown
    for dim in record.rubric.dimensions:
        assert dim.name in md


def test_review_draft_block_is_fenced_markdown(record):
    draft_md = _section(build_view_sections(record), "Review draft (copy-paste)").body_markdown
    assert draft_md.startswith("```markdown\n")
    assert draft_md.rstrip().endswith("```")
    assert "## Summary" in draft_md


def test_compliance_section_shows_triage(record):
    md = _section(build_view_sections(record), "Compliance").body_markdown
    assert "Triage" in md
    assert record.compliance.triage.value in md


def test_all_fixture_papers_render(record):
    """Smoke: every fixture record, including the FAIL case, renders."""
    for fixture in (
        "paper_01_numbered_refs",
        "paper_02_doi_heavy",
        "paper_03_bulleted_refs",
        "paper_04_no_refs_section",  # compliance FAIL case
        "paper_05_mixed_refs",
    ):
        md = (FIXTURES_DIR / f"{fixture}.md").read_text(encoding="utf-8")
        paper = parse_markdown(md, source_name=fixture)
        rec = run_pipeline(paper, load_venue_config(CONFIGS_DIR / "neurips.yaml"))
        sections = build_view_sections(rec)
        assert [s.title for s in sections] == EXPECTED_TITLES
        for s in sections:
            assert s.body_markdown.strip()


def test_dashboard_module_imports_without_streamlit():
    """Importing the module must not require streamlit (lazy import).

    We assert the import succeeds — if streamlit were eagerly imported,
    this test would fail in an env without the `[dashboard]` extra.
    """
    from evalit_4me.dashboard import app

    assert hasattr(app, "build_view_sections")
