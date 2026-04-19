"""Typer CLI for evalit-4me.

Subcommands:
    evalit review <paper>         — run the pipeline, print review markdown
    evalit rubric init <path>     — scaffold a custom venue config
    evalit rubric validate <path> — validate a config against the schema
    evalit audit <db>             — produce a fairness audit JSON over a log DB
    evalit dashboard [record]     — launch Streamlit UI (requires [dashboard] extra)
    evalit version                — print version

All subcommands use `--config` to point at a venue YAML. Defaults to the
shipped NeurIPS config.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from evalit_4me import __version__
from evalit_4me.audit.fairness import build_fairness_report_from_db, report_to_dict
from evalit_4me.config import load_venue_config
from evalit_4me.formatters.json_out import dump_record_json
from evalit_4me.formatters.reviewer import format_review_draft, render_review_markdown
from evalit_4me.ingest.parser import parse_markdown, parse_pdf
from evalit_4me.stages.orchestrate import PipelineOptions, run_pipeline
from evalit_4me.stages.rubric import init_template, validate_config_file
from evalit_4me.storage.sqlite_log import SqliteLog

app = typer.Typer(help="evalit-4me: 5-layer AI evaluation framework for academic peer review.")
rubric_app = typer.Typer(help="Rubric config helpers.")
app.add_typer(rubric_app, name="rubric")

_DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "neurips.yaml"


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Print the installed evalit-4me version."""
    typer.echo(__version__)


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------


@app.command()
def review(
    paper: Path = typer.Argument(
        ..., exists=True, readable=True, help="Path to a PDF or markdown file."
    ),
    config: Path = typer.Option(_DEFAULT_CONFIG, "--config", "-c", help="Venue config YAML."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write the full EvaluationRecord JSON to this path."
    ),
    log_db: Path | None = typer.Option(
        None, "--log-db", help="Append the record to a SQLite audit log."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Skip LLM and network calls."),
) -> None:
    """Run the evaluation pipeline and print the reviewer markdown."""
    cfg = load_venue_config(config)
    paper_obj = _load_paper(paper)
    # v0.1: `--dry-run` and "no flag" currently behave the same — real LLM +
    # HTTP wiring lands in v0.1.1 once cost-gating is finalized. The flag
    # is already exposed so the semantics don't move later.
    _ = dry_run  # reserved for the provider/http_client toggles
    record = run_pipeline(
        paper_obj,
        cfg,
        provider=None,
        http_client=None,
        options=PipelineOptions(),
    )
    draft = format_review_draft(record)
    md = render_review_markdown(draft)
    typer.echo(md)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(dump_record_json(record), encoding="utf-8")
        typer.echo(f"\nWrote record JSON to {output}", err=True)

    if log_db is not None:
        log = SqliteLog(log_db)
        new_id = log.save(record)
        typer.echo(f"Logged evaluation id={new_id} to {log_db}", err=True)


def _load_paper(path: Path):
    if path.suffix.lower() == ".pdf":
        return parse_pdf(path)
    return parse_markdown(path.read_text(encoding="utf-8"), source_name=path.stem)


# ---------------------------------------------------------------------------
# rubric init / validate
# ---------------------------------------------------------------------------


@rubric_app.command("init")
def rubric_init(
    out: Path = typer.Argument(..., help="Destination path for the scaffolded YAML."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace an existing file."),
) -> None:
    """Scaffold a custom venue config from the shipped template."""
    try:
        dest = init_template(out, overwrite=overwrite)
    except FileExistsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Wrote template to {dest}")


@rubric_app.command("validate")
def rubric_validate(
    path: Path = typer.Argument(..., exists=True, readable=True, help="YAML to validate."),
) -> None:
    """Validate a venue config against the full schema."""
    try:
        cfg = validate_config_file(path)
    except Exception as exc:
        typer.echo(f"Invalid config: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"OK: venue={cfg.venue}, rubric={cfg.rubric.id}, {len(cfg.rubric.dimensions)} dimension(s)"
    )


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


@app.command()
def audit(
    input_db: Path = typer.Option(
        ..., "--input", "-i", exists=True, readable=True, help="SQLite audit log path."
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write JSON report here; otherwise stdout."
    ),
    threshold: float = typer.Option(
        0.55, "--threshold", help="Accept-threshold for disparate-impact computation."
    ),
) -> None:
    """Produce a fairness audit JSON over an evaluation log DB."""
    report = build_fairness_report_from_db(input_db, accept_threshold=threshold)
    payload = json.dumps(report_to_dict(report), indent=2)
    if output is None:
        typer.echo(payload)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
        typer.echo(f"Wrote fairness report to {output}", err=True)


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------


@app.command()
def dashboard(
    record: Path | None = typer.Argument(
        None, exists=True, readable=True, help="Optional pre-loaded record JSON."
    ),
) -> None:
    """Launch the Streamlit reviewer view. Requires the `[dashboard]` extra."""
    try:
        from streamlit.web import cli as stcli  # type: ignore[import-not-found]
    except ImportError as exc:
        typer.echo(
            "Streamlit is not installed. Install with: pip install 'evalit-4me[dashboard]'",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    app_path = str(Path(__file__).resolve().parent / "dashboard" / "app.py")
    args = ["streamlit", "run", app_path]
    if record is not None:
        args.extend(["--", "--record", str(record)])
    sys.argv = args
    sys.exit(stcli.main())  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
