"""SQLite log tests — schema + round-trip + query_scores + JSONL dump."""

from __future__ import annotations

import json
from pathlib import Path

from evalit_4me.config import load_venue_config
from evalit_4me.contracts import EvaluationRecord
from evalit_4me.ingest.parser import parse_markdown
from evalit_4me.stages.orchestrate import run_pipeline
from evalit_4me.storage.sqlite_log import SqliteLog, dump_as_jsonl

CONFIGS_DIR = Path(__file__).parents[3] / "configs"
FIXTURES_DIR = Path(__file__).parents[2] / "fixtures" / "markdown"


def _make_record(fixture: str = "paper_01_numbered_refs") -> EvaluationRecord:
    md = (FIXTURES_DIR / f"{fixture}.md").read_text(encoding="utf-8")
    paper = parse_markdown(md, source_name=fixture)
    return run_pipeline(paper, load_venue_config(CONFIGS_DIR / "neurips.yaml"))


def test_save_and_load_round_trip(tmp_path: Path):
    log = SqliteLog(tmp_path / "audit.sqlite")
    record = _make_record()
    new_id = log.save(record)
    loaded = log.load(new_id)
    assert loaded.paper.id == record.paper.id
    assert loaded.compliance.triage == record.compliance.triage


def test_iter_records_is_ordered_by_id(tmp_path: Path):
    log = SqliteLog(tmp_path / "audit.sqlite")
    r1 = _make_record("paper_01_numbered_refs")
    r2 = _make_record("paper_02_doi_heavy")
    log.save(r1)
    log.save(r2)
    rs = list(log.iter_records())
    assert len(rs) == 2
    assert rs[0].paper.id == r1.paper.id
    assert rs[1].paper.id == r2.paper.id


def test_count(tmp_path: Path):
    log = SqliteLog(tmp_path / "audit.sqlite")
    assert log.count() == 0
    log.save(_make_record())
    log.save(_make_record("paper_02_doi_heavy"))
    assert log.count() == 2


def test_query_scores_returns_flat_rows(tmp_path: Path):
    log = SqliteLog(tmp_path / "audit.sqlite")
    r = _make_record()
    log.save(r)
    rows = log.query_scores()
    assert len(rows) == 1
    row = rows[0]
    assert row["paper_id"] == r.paper.id
    assert r.rubric is not None
    assert row["rubric_raw_total"] == r.rubric.raw_total
    assert row["compliance_triage"] == r.compliance.triage.value


def test_load_missing_raises(tmp_path: Path):
    import pytest

    log = SqliteLog(tmp_path / "audit.sqlite")
    with pytest.raises(KeyError):
        log.load(999)


def test_reopening_db_preserves_data(tmp_path: Path):
    db = tmp_path / "audit.sqlite"
    log = SqliteLog(db)
    log.save(_make_record())
    reopened = SqliteLog(db)
    assert reopened.count() == 1


def test_dump_as_jsonl(tmp_path: Path):
    db = tmp_path / "audit.sqlite"
    out = tmp_path / "records.jsonl"
    log = SqliteLog(db)
    log.save(_make_record("paper_01_numbered_refs"))
    log.save(_make_record("paper_02_doi_heavy"))
    n = dump_as_jsonl(db, out)
    assert n == 2
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert "paper" in parsed
