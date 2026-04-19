"""JSON dump tests — valid JSON, round-trips."""

from __future__ import annotations

import json
from pathlib import Path

from evalit_4me.config import load_venue_config
from evalit_4me.contracts import EvaluationRecord
from evalit_4me.formatters.json_out import dump_record_json, dump_review_json
from evalit_4me.formatters.reviewer import format_review_draft
from evalit_4me.ingest.parser import parse_markdown
from evalit_4me.stages.orchestrate import run_pipeline

CONFIGS_DIR = Path(__file__).parents[3] / "configs"
FIXTURES_DIR = Path(__file__).parents[2] / "fixtures" / "markdown"


def test_record_json_is_valid_and_round_trips():
    md = (FIXTURES_DIR / "paper_01_numbered_refs.md").read_text(encoding="utf-8")
    paper = parse_markdown(md, source_name="paper_01")
    record = run_pipeline(paper, load_venue_config(CONFIGS_DIR / "neurips.yaml"))

    raw = dump_record_json(record)
    parsed = json.loads(raw)
    assert "paper" in parsed
    # Round-trip: parse back into contract.
    rebuilt = EvaluationRecord.model_validate(parsed)
    assert rebuilt.paper.id == record.paper.id


def test_review_json():
    md = (FIXTURES_DIR / "paper_01_numbered_refs.md").read_text(encoding="utf-8")
    paper = parse_markdown(md, source_name="paper_01")
    record = run_pipeline(paper, load_venue_config(CONFIGS_DIR / "neurips.yaml"))
    draft = format_review_draft(record)
    raw = dump_review_json(draft)
    parsed = json.loads(raw)
    assert parsed["paper_id"] == record.paper.id
    assert "recommendation" in parsed
