"""Cost tracker: pricing lookup + persistence across restarts."""

from __future__ import annotations

from pathlib import Path

import pytest

from evalit_4me.llm.cost import PRICING, CostTracker, estimate_cost


def test_estimate_cost_known_model():
    # Sonnet 4.6: 3.0 in, 15.0 out per 1M tokens.
    cost = estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.0)


def test_estimate_cost_unknown_model_is_zero():
    assert estimate_cost("nonexistent-model-xyz", 1000, 1000) == 0.0


def test_pricing_table_has_expected_models():
    for m in ("claude-sonnet-4-6", "claude-opus-4-6", "gpt-4o", "gpt-4o-mini"):
        assert m in PRICING


def test_cost_tracker_record_and_total(tmp_path: Path):
    log = tmp_path / "cost.jsonl"
    tracker = CostTracker(log_path=log)
    tracker.record(
        provider="anthropic",
        model="claude-sonnet-4-6",
        prompt_tokens=1000,
        completion_tokens=500,
    )
    tracker.record(
        provider="openai",
        model="gpt-4o-mini",
        prompt_tokens=2000,
        completion_tokens=1000,
    )
    total = tracker.total_cost_usd()
    assert total > 0.0
    by_model = tracker.totals_by_model()
    assert set(by_model.keys()) == {"claude-sonnet-4-6", "gpt-4o-mini"}


def test_cost_tracker_persists_across_instances(tmp_path: Path):
    log = tmp_path / "cost.jsonl"
    t1 = CostTracker(log_path=log)
    t1.record(
        provider="openai",
        model="gpt-4o",
        prompt_tokens=1000,
        completion_tokens=500,
    )
    total1 = t1.total_cost_usd()

    # Simulate process restart: brand-new tracker pointing at the same file.
    t2 = CostTracker(log_path=log)
    assert t2.total_cost_usd() == pytest.approx(total1)
    assert len(t2.entries()) == 1


def test_cost_tracker_records_cache_hits_with_zero_cost(tmp_path: Path):
    # If caller overrides cost_usd to 0 (cache-hit case), we still append
    # an entry so audit trails remain complete.
    log = tmp_path / "cost.jsonl"
    tracker = CostTracker(log_path=log)
    tracker.record(
        provider="stub",
        model="stub-model",
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=0.0,
    )
    assert len(tracker.entries()) == 1
    assert tracker.total_cost_usd() == 0.0
