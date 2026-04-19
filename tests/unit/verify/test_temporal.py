"""Temporal consistency checks."""

from __future__ import annotations

from evalit_4me.contracts import Paper, PaperMetadata, Reference
from evalit_4me.stages.verify.temporal import check_temporal_consistency


def _paper_with_refs(paper_year: int | None, ref_years: list[int | None]) -> Paper:
    refs = [Reference(id=f"r{i}", raw=".", year=y) for i, y in enumerate(ref_years)]
    return Paper(
        id="p",
        metadata=PaperMetadata(title="T", year=paper_year),
        references=refs,
    )


def test_no_issues_when_all_refs_earlier():
    paper = _paper_with_refs(2020, [2015, 2018, 2019])
    assert check_temporal_consistency(paper) == []


def test_flags_future_citation():
    paper = _paper_with_refs(2020, [2021])
    issues = check_temporal_consistency(paper)
    assert len(issues) == 1
    assert issues[0].reference_id == "r0"
    assert "after" in issues[0].reason.lower()


def test_falls_back_to_current_year_when_paper_year_missing():
    paper = _paper_with_refs(None, [2027])
    issues = check_temporal_consistency(paper, current_year=2025)
    assert len(issues) == 1
    assert issues[0].paper_year == 2025


def test_none_ref_years_ignored():
    paper = _paper_with_refs(2020, [None, 2018, None])
    assert check_temporal_consistency(paper) == []


def test_max_age_years_flags_very_old():
    paper = _paper_with_refs(2020, [1940, 2000, 2018])
    issues = check_temporal_consistency(paper, max_age_years=50)
    # 1940 is > 50 years before 2020.
    assert len(issues) == 1
    assert issues[0].reference_id == "r0"


def test_same_year_is_fine():
    paper = _paper_with_refs(2020, [2020])
    assert check_temporal_consistency(paper) == []
