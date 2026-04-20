"""CLI smoke tests — each Typer subcommand runs on a fixture."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from evalit_4me import __version__
from evalit_4me.cli import app

CONFIGS_DIR = Path(__file__).parents[2] / "configs"
FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "markdown"

runner = CliRunner()


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


def test_version_prints_installed_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_lists_all_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("review", "rubric", "audit", "version"):
        assert cmd in result.stdout


# ---------------------------------------------------------------------------
# review (on a markdown fixture, dry-run)
# ---------------------------------------------------------------------------


def test_review_on_markdown_fixture_dry_run():
    paper = FIXTURES_DIR / "paper_01_numbered_refs.md"
    result = runner.invoke(app, ["review", str(paper), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "## Summary" in result.stdout
    assert "## Overall score" in result.stdout


def test_review_writes_output_json(tmp_path: Path):
    paper = FIXTURES_DIR / "paper_01_numbered_refs.md"
    out = tmp_path / "record.json"
    result = runner.invoke(app, ["review", str(paper), "--dry-run", "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "paper" in data


def test_review_logs_to_sqlite(tmp_path: Path):
    paper = FIXTURES_DIR / "paper_01_numbered_refs.md"
    db = tmp_path / "audit.sqlite"
    result = runner.invoke(app, ["review", str(paper), "--dry-run", "--log-db", str(db)])
    assert result.exit_code == 0, result.output
    assert db.exists()

    from evalit_4me.storage.sqlite_log import SqliteLog

    log = SqliteLog(db)
    assert log.count() == 1


# ---------------------------------------------------------------------------
# rubric init / validate
# ---------------------------------------------------------------------------


def test_rubric_init_scaffolds_file(tmp_path: Path):
    out = tmp_path / "custom.yaml"
    result = runner.invoke(app, ["rubric", "init", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()


def test_rubric_init_refuses_existing_without_overwrite(tmp_path: Path):
    out = tmp_path / "custom.yaml"
    out.write_text("existing")
    result = runner.invoke(app, ["rubric", "init", str(out)])
    assert result.exit_code == 1


def test_rubric_init_overwrite(tmp_path: Path):
    out = tmp_path / "custom.yaml"
    out.write_text("existing")
    result = runner.invoke(app, ["rubric", "init", str(out), "--overwrite"])
    assert result.exit_code == 0


def test_rubric_validate_on_shipped_config():
    result = runner.invoke(app, ["rubric", "validate", str(CONFIGS_DIR / "neurips.yaml")])
    assert result.exit_code == 0, result.output
    assert "venue=neurips" in result.stdout


def test_rubric_validate_rejects_bad_config(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("venue: x\n", encoding="utf-8")
    result = runner.invoke(app, ["rubric", "validate", str(bad)])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


def test_audit_produces_json_on_stdout(tmp_path: Path):
    """Exit gate: `evalit audit --input <db>` produces JSON fairness report."""
    paper = FIXTURES_DIR / "paper_01_numbered_refs.md"
    db = tmp_path / "audit.sqlite"
    runner.invoke(app, ["review", str(paper), "--dry-run", "--log-db", str(db)])

    result = runner.invoke(app, ["audit", "--input", str(db)])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert parsed["n_records"] == 1
    assert "length_disparate_impact" in parsed


def test_audit_writes_output_file(tmp_path: Path):
    paper = FIXTURES_DIR / "paper_01_numbered_refs.md"
    db = tmp_path / "audit.sqlite"
    runner.invoke(app, ["review", str(paper), "--dry-run", "--log-db", str(db)])
    out = tmp_path / "fairness.json"

    result = runner.invoke(app, ["audit", "--input", str(db), "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    json.loads(out.read_text(encoding="utf-8"))  # valid JSON
