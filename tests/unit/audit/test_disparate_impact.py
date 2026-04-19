"""Disparate-impact tests using synthetic records with known ratios."""

from __future__ import annotations

from pathlib import Path

from evalit_4me.audit.disparate_impact import compute_disparate_impact
from evalit_4me.config import load_venue_config
from evalit_4me.ingest.parser import parse_markdown
from evalit_4me.stages.orchestrate import run_pipeline

CONFIGS_DIR = Path(__file__).parents[3] / "configs"
FIXTURES_DIR = Path(__file__).parents[2] / "fixtures" / "markdown"


def _records_with_bias() -> list:
    """Build a synthetic biased dataset: group A gets score 0.9, B gets 0.1."""
    records = []
    neurips = load_venue_config(CONFIGS_DIR / "neurips.yaml")
    for _ in range(10):
        # Reuse a passing fixture, we'll mutate the rubric score below.
        md = (FIXTURES_DIR / "paper_01_numbered_refs.md").read_text(encoding="utf-8")
        paper = parse_markdown(md)
        records.append(run_pipeline(paper, neurips))
    return records


def test_equal_groups_no_flag():
    records = _records_with_bias()
    # Half group_a, half group_b; all same score => DI = 1.0.
    groups = ["a"] * 5 + ["b"] * 5
    result = compute_disparate_impact(
        records,
        group_fn=lambda r: groups.pop(0),
        score_fn=lambda r: 0.8,
        threshold=0.5,
    )
    assert result.di_ratio == 1.0
    assert result.flagged_4_5ths_rule is False


def test_extreme_bias_triggers_flag():
    records = _records_with_bias()
    # Group a gets all 0.9 (positive), group b gets all 0.1 (negative).
    groups = ["a"] * 5 + ["b"] * 5
    scores = [0.9] * 5 + [0.1] * 5
    group_iter = iter(groups)
    score_iter = iter(scores)
    result = compute_disparate_impact(
        records,
        group_fn=lambda r: next(group_iter),
        score_fn=lambda r: next(score_iter),
        threshold=0.5,
    )
    assert result.di_ratio == 0.0
    assert result.flagged_4_5ths_rule is True


def test_partial_bias_below_80pct():
    """Group a has 5/5 positives, group b has 3/5 -> DI = 0.6, flagged."""
    records = _records_with_bias()
    groups = ["a"] * 5 + ["b"] * 5
    scores = [0.9] * 5 + [0.9, 0.9, 0.9, 0.1, 0.1]
    g_iter = iter(groups)
    s_iter = iter(scores)
    result = compute_disparate_impact(
        records,
        group_fn=lambda r: next(g_iter),
        score_fn=lambda r: next(s_iter),
        threshold=0.5,
    )
    # a: 5/5 = 1.0; b: 3/5 = 0.6; di = 0.6 / 1.0 = 0.6
    assert result.di_ratio == 0.6
    assert result.flagged_4_5ths_rule is True


def test_single_group_returns_no_ratio():
    records = _records_with_bias()
    result = compute_disparate_impact(
        records,
        group_fn=lambda r: "only",
        score_fn=lambda r: 0.8,
        threshold=0.5,
    )
    assert result.di_ratio is None
    assert result.flagged_4_5ths_rule is False


def test_excluded_records_not_counted():
    records = _records_with_bias()
    # Include only first 3 records.
    calls = {"n": 0}

    def group(r):
        calls["n"] += 1
        return "a" if calls["n"] <= 3 else None

    result = compute_disparate_impact(
        records, group_fn=group, score_fn=lambda r: 0.9, threshold=0.5
    )
    # Only 3 records, single group, so di_ratio is None.
    assert result.di_ratio is None
    assert sum(g.n for g in result.group_rates) == 3
