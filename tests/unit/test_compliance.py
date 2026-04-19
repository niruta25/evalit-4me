"""Compliance stage tests — 3 synthetic triage cases + config load + fixture smoke.

Exit-gate checks enforced here:
  * Synthetic PASS / CONDITIONAL / FAIL cases match expected triage
  * Real neurips.yaml loads into a valid ComplianceConfig
  * FAIL propagates on critical violations so the orchestrator can short-circuit
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalit_4me.contracts import Paper, PaperMetadata, Section, Triage
from evalit_4me.ingest.parser import parse_markdown
from evalit_4me.stages.compliance import (
    ComplianceConfig,
    check_compliance,
    load_compliance_config,
)

CONFIGS_DIR = Path(__file__).parents[2] / "configs"
FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "markdown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_config(**overrides) -> ComplianceConfig:
    """Lightweight config for focused unit tests."""
    base = {
        "required_sections": [
            ["abstract"],
            ["introduction"],
            ["method", "methods"],
            ["results", "experiments"],
            ["conclusion"],
        ],
        "word_count_min": 100,
        "word_count_max": 20000,
        "min_references": 3,
        "require_ethics": False,
        "ethics_aliases": [],
        "require_anonymization": False,
    }
    base.update(overrides)
    return ComplianceConfig.model_validate(base)


def _make_section(title: str, text: str = "lorem ipsum dolor sit amet", order: int = 0) -> Section:
    return Section(id=title.lower().replace(" ", "-"), title=title, text=text, order=order)


def _make_paper(
    *,
    section_titles: list[str] | None = None,
    reference_count: int = 5,
    authors: list[str] | None = None,
    abstract: str | None = "This paper proposes something novel.",
    body_per_section: int = 200,
) -> Paper:
    titles = section_titles or [
        "Abstract",
        "Introduction",
        "Method",
        "Results",
        "Conclusion",
    ]
    body = " ".join(["word"] * body_per_section)
    sections = [_make_section(t, body, i) for i, t in enumerate(titles)]
    refs = [
        __import__("evalit_4me.contracts", fromlist=["Reference"]).Reference(
            id=f"r{i}", raw=f"Ref {i}"
        )
        for i in range(reference_count)
    ]
    return Paper(
        id="paper:test",
        metadata=PaperMetadata(title="Test Paper", authors=authors or [], abstract=abstract),
        sections=sections,
        references=refs,
    )


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_real_neurips_yaml_loads():
    config = load_compliance_config(CONFIGS_DIR / "neurips.yaml")
    assert len(config.required_sections) >= 5
    assert config.require_ethics is True
    assert config.require_anonymization is True
    assert config.min_references is not None and config.min_references >= 1


def test_load_config_missing_compliance_block(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("venue: other\n", encoding="utf-8")
    with pytest.raises(ValueError, match="compliance"):
        load_compliance_config(p)


def test_compliance_config_rejects_extra_fields():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ComplianceConfig.model_validate({"mystery": 1})


# ---------------------------------------------------------------------------
# Three synthetic triage cases
# ---------------------------------------------------------------------------


def test_pass_case():
    """All required sections present, refs present, word count in range, no soft violations."""
    paper = _make_paper()
    report = check_compliance(paper, _minimal_config())
    assert report.triage == Triage.PASS
    assert report.issues == []
    assert all(c.passed for c in report.section_checks)
    assert all(c.passed for c in report.format_checks)


def test_conditional_case_word_count_out_of_range():
    """Soft violation only — word count out of bounds — CONDITIONAL."""
    paper = _make_paper(body_per_section=5)  # ~25 words total
    report = check_compliance(paper, _minimal_config())
    assert report.triage == Triage.CONDITIONAL
    assert any("Word count" in issue for issue in report.issues)
    # Section checks still passed.
    assert all(c.passed for c in report.section_checks)


def test_fail_case_missing_section():
    """Critical violation — required section missing — FAIL."""
    paper = _make_paper(
        section_titles=["Abstract", "Introduction", "Results", "Conclusion"]  # no Method
    )
    report = check_compliance(paper, _minimal_config())
    assert report.triage == Triage.FAIL
    assert any("method" in issue.lower() for issue in report.issues)


def test_fail_case_too_few_references():
    paper = _make_paper(reference_count=1)
    report = check_compliance(paper, _minimal_config(min_references=10))
    assert report.triage == Triage.FAIL
    assert any("references" in issue.lower() for issue in report.issues)


# ---------------------------------------------------------------------------
# Ethics + anonymization toggles
# ---------------------------------------------------------------------------


def test_conditional_when_ethics_required_but_absent():
    paper = _make_paper()
    cfg = _minimal_config(
        require_ethics=True,
        ethics_aliases=["broader impact", "ethics", "limitations"],
    )
    report = check_compliance(paper, cfg)
    assert report.triage == Triage.CONDITIONAL
    assert any("Ethics" in i for i in report.issues)


def test_pass_when_ethics_present_via_alias():
    paper = _make_paper(
        section_titles=[
            "Abstract",
            "Introduction",
            "Method",
            "Results",
            "Conclusion",
            "Broader Impact",
        ]
    )
    cfg = _minimal_config(require_ethics=True, ethics_aliases=["broader impact", "ethics"])
    report = check_compliance(paper, cfg)
    assert report.triage == Triage.PASS


def test_conditional_when_not_anonymized():
    paper = _make_paper(authors=["Jane Doe", "John Smith"])
    cfg = _minimal_config(require_anonymization=True)
    report = check_compliance(paper, cfg)
    assert report.triage == Triage.CONDITIONAL
    assert any("anonym" in i.lower() for i in report.issues)


def test_pass_when_explicitly_anonymized_author():
    paper = _make_paper(authors=["Anonymous Authors"])
    cfg = _minimal_config(require_anonymization=True)
    report = check_compliance(paper, cfg)
    assert report.triage == Triage.PASS


# ---------------------------------------------------------------------------
# Interaction: FAIL wins over CONDITIONAL
# ---------------------------------------------------------------------------


def test_fail_wins_over_soft_violations():
    """A critical violation + a soft violation must still produce FAIL."""
    paper = _make_paper(
        section_titles=["Abstract", "Introduction", "Results", "Conclusion"],  # missing Method
        body_per_section=5,  # also short
    )
    report = check_compliance(paper, _minimal_config())
    assert report.triage == Triage.FAIL


# ---------------------------------------------------------------------------
# Smoke test on shipped markdown fixtures
# ---------------------------------------------------------------------------


def test_fixture_papers_run_without_raising():
    """Every Chunk 1.3 fixture must parse + pass compliance (even if triage varies)."""
    cfg = load_compliance_config(CONFIGS_DIR / "neurips.yaml")
    md_files = sorted(FIXTURES_DIR.glob("*.md"))
    assert len(md_files) == 5
    for md in md_files:
        paper = parse_markdown(md.read_text(encoding="utf-8"), source_name=md.stem)
        report = check_compliance(paper, cfg)
        assert report.triage in (Triage.PASS, Triage.CONDITIONAL, Triage.FAIL)
        assert isinstance(report.issues, list)
