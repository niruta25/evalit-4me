"""Fairness report tests — length correlation + report shape."""

from __future__ import annotations

from pathlib import Path

from evalit_4me.audit.fairness import (
    build_fairness_report,
    build_fairness_report_from_db,
    report_to_dict,
)
from evalit_4me.config import load_venue_config
from evalit_4me.ingest.parser import parse_markdown
from evalit_4me.stages.orchestrate import run_pipeline
from evalit_4me.storage.sqlite_log import SqliteLog

CONFIGS_DIR = Path(__file__).parents[3] / "configs"
FIXTURES_DIR = Path(__file__).parents[2] / "fixtures" / "markdown"


def _all_fixture_records():
    cfg = load_venue_config(CONFIGS_DIR / "neurips.yaml")
    records = []
    for md in sorted(FIXTURES_DIR.glob("*.md")):
        paper = parse_markdown(md.read_text(encoding="utf-8"), source_name=md.stem)
        records.append(run_pipeline(paper, cfg))
    return records


def test_report_contains_all_keys():
    records = _all_fixture_records()
    report = build_fairness_report(records)
    assert report.n_records == len(records)
    assert report.length_score_pearson is not None or report.length_score_rationale
    assert "note" in report.position_bias
    assert "di_ratio" in report.length_disparate_impact


def test_report_to_dict_is_json_serializable():
    import json

    report = build_fairness_report(_all_fixture_records())
    raw = json.dumps(report_to_dict(report))
    assert "n_records" in raw
    assert "length_disparate_impact" in raw


def test_too_few_records_correlation_is_none():
    report = build_fairness_report([])
    assert report.length_score_pearson is None
    assert "Too few" in report.length_score_rationale


def test_end_to_end_via_db(tmp_path: Path):
    """Exit gate: `evalit audit --input <db>` produces JSON fairness report."""
    db = tmp_path / "audit.sqlite"
    log = SqliteLog(db)
    for r in _all_fixture_records():
        log.save(r)
    report = build_fairness_report_from_db(db)
    import json

    assert report.n_records == len(list(log.iter_records()))
    # Ensure JSON serialization for CLI output.
    json.dumps(report_to_dict(report))


def test_disparate_impact_on_synthetic_biased_dataset(tmp_path: Path):
    """Construct a dataset where 'long' papers always pass threshold but
    'short' ones never do -> DI = 0 -> flagged."""
    from evalit_4me.audit.disparate_impact import compute_disparate_impact

    records = _all_fixture_records()
    # Use fixture sizes to infer long/short; force scores accordingly.
    group = ["long", "long", "short", "short", "short"][: len(records)]
    scores = [0.9, 0.9, 0.1, 0.1, 0.1][: len(records)]
    g_iter = iter(group)
    s_iter = iter(scores)
    result = compute_disparate_impact(
        records,
        group_fn=lambda r: next(g_iter),
        score_fn=lambda r: next(s_iter),
        threshold=0.5,
    )
    assert result.di_ratio == 0.0
    assert result.flagged_4_5ths_rule is True
