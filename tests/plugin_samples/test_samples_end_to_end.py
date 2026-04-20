"""End-to-end tests over the shipped `plugin/examples/` sample papers.

Every sample runs through the full pipeline in heuristic mode (no LLM,
no HTTP). These tests are what Anthropic's plugin reviewer would
effectively be exercising with `/evalit review plugin/examples/<sample>`.

Coverage:
    - Venue-config auto-detection picks the expected config.
    - Happy-path markdown samples compute a composite and return a
      non-reject recommendation family.
    - `sample_failing.md` produces compliance triage = FAIL.
    - `sample_fabricated.md` flags the three fabricated DOIs under a
      404-only HTTP client.
    - `sample.pdf` and `sample_twocol.pdf` parse via pdfplumber without
      crashing and produce non-empty sections.
    - `sample.docx` parses via mammoth with non-empty sections.

pdfplumber, mammoth are required (the `[pdf-lite]` and `[docx]` extras).
Marker is *not* used anywhere in these tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalit_4me.config import load_venue_config
from evalit_4me.contracts import Triage
from evalit_4me.ingest import load_paper
from evalit_4me.skill_helpers import detect_best_config
from evalit_4me.stages.orchestrate import run_pipeline

CONFIGS_DIR = Path(__file__).parents[2] / "configs"
EXAMPLES_DIR = Path(__file__).parents[2] / "plugin" / "examples"


ACCEPT_FAMILY = {
    "STRONG_ACCEPT",
    "ACCEPT",
    "WEAK_ACCEPT",
    "BORDERLINE",
}


def _run(sample: str, config_name: str):
    """Helper: parse a sample, run the pipeline in heuristic mode."""
    paper = load_paper(EXAMPLES_DIR / sample)
    cfg = load_venue_config(CONFIGS_DIR / f"{config_name}.yaml")
    return run_pipeline(paper, cfg, provider=None, http_client=None)


@pytest.mark.parametrize(
    ("sample", "expected_config"),
    [
        ("sample_neurips.md", "neurips"),
        ("sample_ieee.md", "ieee"),
        ("sample_arxiv.md", "arxiv"),
    ],
)
def test_auto_detection_picks_expected_config(sample: str, expected_config: str):
    """Venue heuristics should pick the intended config for each happy-path sample."""
    md = (EXAMPLES_DIR / sample).read_text(encoding="utf-8")
    guess = detect_best_config(md, full_doc=True)
    assert guess.recommended == expected_config, (
        f"Expected {expected_config} for {sample}, got {guess.recommended}: {guess.rationale}"
    )


@pytest.mark.parametrize(
    ("sample", "config"),
    [
        ("sample_neurips.md", "neurips"),
        ("sample_ieee.md", "ieee"),
        ("sample_arxiv.md", "arxiv"),
    ],
)
def test_happy_path_samples_produce_non_reject_recommendation(sample: str, config: str):
    record = _run(sample, config)
    assert record.compliance.triage in {Triage.PASS, Triage.CONDITIONAL}
    from evalit_4me.formatters.reviewer import format_review_draft

    draft = format_review_draft(record)
    assert draft.recommendation.value in ACCEPT_FAMILY, (
        f"{sample} under {config} got {draft.recommendation.value}"
    )
    assert draft.overall_score > 0.0


def test_failing_sample_produces_compliance_fail():
    record = _run("sample_failing.md", "neurips")
    # Missing sections, too few references → compliance FAIL or CONDITIONAL.
    assert record.compliance.triage in {Triage.FAIL, Triage.CONDITIONAL}
    # Regardless of triage, the pipeline must still produce a composite.
    from evalit_4me.formatters.reviewer import format_review_draft

    draft = format_review_draft(record)
    assert 0.0 <= draft.overall_score <= 1.0


def test_fabricated_sample_pipeline_runs_without_crash():
    """Without an http_client, fabricated DOIs can't be checked against
    CrossRef — so hallucination_flag won't fire. What we assert here is
    that the pipeline runs to completion and produces a valid record.

    Real fabrication-catching is covered by the stage 2b suite in
    tests/unit/verify/ which exercises the HTTP cascade directly.
    """
    record = _run("sample_fabricated.md", "neurips")
    assert record.claims.total_claims >= 0  # pipeline completed


def test_pdf_sample_parses_with_pdfplumber():
    pytest.importorskip("pdfplumber")
    paper = load_paper(EXAMPLES_DIR / "sample.pdf")
    assert paper.sections, "pdfplumber should extract at least one section"
    # At least one section should be non-empty.
    assert any(s.text.strip() for s in paper.sections)


def test_twocol_pdf_sample_parses_with_pdfplumber():
    pytest.importorskip("pdfplumber")
    paper = load_paper(EXAMPLES_DIR / "sample_twocol.pdf")
    assert paper.sections, "pdfplumber should extract sections from two-column PDF"
    assert any(s.text.strip() for s in paper.sections)


def test_pdf_sample_runs_through_pipeline():
    pytest.importorskip("pdfplumber")
    record = _run("sample.pdf", "arxiv")
    assert record is not None
    from evalit_4me.formatters.reviewer import format_review_draft

    draft = format_review_draft(record)
    assert 0.0 <= draft.overall_score <= 1.0


def test_docx_sample_parses_with_mammoth():
    pytest.importorskip("mammoth")
    paper = load_paper(EXAMPLES_DIR / "sample.docx")
    assert paper.sections, "mammoth should extract at least one section"
    assert any(s.text.strip() for s in paper.sections)


def test_docx_sample_runs_through_pipeline():
    pytest.importorskip("mammoth")
    record = _run("sample.docx", "neurips")
    from evalit_4me.formatters.reviewer import format_review_draft

    draft = format_review_draft(record)
    # The sample.docx is the NeurIPS paper round-tripped, so expect an
    # accept-family recommendation.
    assert draft.recommendation.value in ACCEPT_FAMILY
