"""Orchestrator tests — full pipeline with stub provider + dry-run path."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from evalit_4me.config import load_venue_config
from evalit_4me.contracts import EvaluationRecord, Recommendation, Triage
from evalit_4me.ingest.parser import parse_markdown
from evalit_4me.llm.stub import StubProvider
from evalit_4me.stages.orchestrate import PipelineOptions, run_pipeline

CONFIGS_DIR = Path(__file__).parents[3] / "configs"
FIXTURES_DIR = Path(__file__).parents[2] / "fixtures" / "markdown"


def _load_neurips():
    return load_venue_config(CONFIGS_DIR / "neurips.yaml")


def _load_paper(name: str):
    md = (FIXTURES_DIR / f"{name}.md").read_text(encoding="utf-8")
    return parse_markdown(md, source_name=name)


def test_dry_run_no_network_no_llm_under_5_seconds():
    """Exit gate: `evalit review paper.pdf --dry-run` produces end-to-end
    output in under 5 seconds, no real API calls."""
    paper = _load_paper("paper_01_numbered_refs")
    config = _load_neurips()
    start = time.perf_counter()
    record = run_pipeline(paper, config, provider=None, http_client=None)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"dry-run took {elapsed:.2f}s (>5s ceiling)"
    assert isinstance(record, EvaluationRecord)
    # No LLM -> no models recorded.
    assert record.provenance.llm_models == {}
    # Depth + rubric must still be populated.
    assert record.depth is not None
    assert record.rubric is not None


def test_stub_provider_runs_without_raising():
    """Exit gate: full-pipeline test with stub LLM on 1 arXiv-like paper."""
    paper = _load_paper("paper_02_doi_heavy")
    config = _load_neurips()
    record = run_pipeline(paper, config, provider=StubProvider(), http_client=None)
    assert record.depth is not None
    assert record.rubric is not None
    # With the stub, claims are empty (stub returns non-JSON), but the
    # pipeline still produces a valid record.
    assert record.claims.total_claims == 0


def test_compliance_fail_short_circuits():
    """A paper with fewer than `min_references` refs triages FAIL and
    skips Stage 2 (no claim work) while still producing depth + rubric."""
    paper = _load_paper("paper_04_no_refs_section")  # 0 references -> FAIL
    config = _load_neurips()
    record = run_pipeline(paper, config)
    assert record.compliance.triage == Triage.FAIL
    assert record.claims.total_claims == 0
    assert record.depth is not None
    assert record.rubric is not None


def test_provenance_is_populated():
    paper = _load_paper("paper_01_numbered_refs")
    config = _load_neurips()
    record = run_pipeline(paper, config)
    assert record.provenance.evalit_version
    assert len(record.provenance.config_hash) == 16  # sha256 first 16 chars
    assert record.provenance.seeds["decompose"] == 0


def test_same_config_produces_same_hash():
    paper = _load_paper("paper_01_numbered_refs")
    config = _load_neurips()
    r1 = run_pipeline(paper, config)
    r2 = run_pipeline(paper, config)
    assert r1.provenance.config_hash == r2.provenance.config_hash


@pytest.mark.parametrize(
    "fixture_name",
    [
        "paper_01_numbered_refs",
        "paper_02_doi_heavy",
        "paper_03_bulleted_refs",
        "paper_05_mixed_refs",
    ],
)
def test_pipeline_on_passing_fixtures(fixture_name: str):
    """Each fixture (except paper_04 which FAILs) produces a full record."""
    paper = _load_paper(fixture_name)
    config = _load_neurips()
    record = run_pipeline(paper, config)
    assert record.rubric is not None
    assert 0.0 <= record.rubric.raw_total <= 1.0
    assert 0.0 <= record.rubric.bias_adjusted_total <= 1.0


def test_pipeline_options_respected():
    """`PipelineOptions.include_entailment=False` shouldn't touch the
    entailment path; compatible with `http_client=None` too."""
    paper = _load_paper("paper_01_numbered_refs")
    config = _load_neurips()
    record = run_pipeline(
        paper,
        config,
        options=PipelineOptions(include_entailment=False, llm_model="custom-model"),
    )
    # include_entailment=False + http_client=None means zero entailment work.
    assert record.claims.total_claims == 0  # no provider, no decomposition.


def test_compliance_fail_surfaces_as_warning_not_forced_rec():
    """Composite-score chunk 1.14 change: compliance FAIL puts a warning
    banner on the draft but does NOT force STRONG_REJECT. The composite
    already weights compliance proportionally."""
    from evalit_4me.formatters.reviewer import format_review_draft

    paper = _load_paper("paper_04_no_refs_section")
    config = _load_neurips()
    record = run_pipeline(paper, config)
    draft = format_review_draft(record)
    assert draft.compliance_warning is not None
    assert "Compliance" in draft.compliance_warning
    # Recommendation must be derived from the composite score, not the triage.
    # For a 0-references fixture the composite will be low, but the *mapping*
    # must not be bypassed to STRONG_REJECT unconditionally.
    assert isinstance(draft.recommendation, Recommendation)
