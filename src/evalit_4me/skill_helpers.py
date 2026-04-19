"""Shared helpers for the Claude skill + MCP server.

All three "skill behaviors" are implemented here and exposed in two
surfaces:

    1. `integrations/claude-code-skill/helpers/*.py` — thin CLI wrappers
       around these functions (Claude Code's SKILL.md shells out to them).
    2. `src/evalit_4me/mcp_server/server.py` — MCP tools that call into
       these same helpers (Claude Desktop runs this as a stdio server).

Functions:

    detect_best_config(paper)            -> "ieee" | "arxiv" | "neurips"
    run_multi_config(pdf, configs, ...)  -> list[(config, record_path)]
    compare_records(record_paths)        -> side-by-side markdown table
    recompute_composite(record_path, weights_dict) -> CompositeScore + new draft

Output layout (matches user spec):

    ~/evalit-reports/<YYYY-MM-DD>-<paper-slug>/
    ├── <config>.json     (full EvaluationRecord)
    ├── <config>.html     (static HTML report)
    ├── <config>.md       (review draft)
    └── comparison.md     (cross-config comparison, when multiple)
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from evalit_4me.config import ScoringConfig, load_venue_config
from evalit_4me.contracts import EvaluationRecord
from evalit_4me.formatters import (
    dump_record_json,
    format_review_draft,
    render_report_html,
    render_review_markdown,
)
from evalit_4me.ingest.parser import parse_markdown, parse_pdf
from evalit_4me.stages.orchestrate import PipelineOptions, run_pipeline
from evalit_4me.stages.scoring import composite_score
from evalit_4me.stages.verify import HTTPClient

# ---------------------------------------------------------------------------
# Shipped configs
# ---------------------------------------------------------------------------

SHIPPED_CONFIGS = ("neurips", "arxiv", "ieee")


def configs_dir() -> Path:
    """Directory containing shipped YAML configs. Works in dev install."""
    return Path(__file__).resolve().parents[2] / "configs"


def config_path(name: str) -> Path:
    p = configs_dir() / f"{name}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"Unknown config {name!r}; tried {p}")
    return p


# ---------------------------------------------------------------------------
# Auto-detect best venue config from paper content
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigGuess:
    recommended: str  # one of SHIPPED_CONFIGS
    confidence: float  # 0..1
    rationale: str


# Roman numeral section headers (`I.`, `II.`, `III.`, ...) are the IEEE signal.
_IEEE_RE = re.compile(r"^\s*[IVX]+\.\s+[A-Z][A-Z \-]{2,}\s*$", re.MULTILINE)
_ARXIV_RE = re.compile(
    r"\barXiv[:\s]\d{4}\.\d{4,5}(?:v\d+)?|arxiv\.org/abs/\d{4}\.\d{4,5}(?:v\d+)?",
    re.IGNORECASE,
)
_NEURIPS_HINTS = re.compile(
    r"broader\s+impact|societal\s+impact|checklist\s+for\s+authors", re.IGNORECASE
)


def detect_best_config(markdown: str) -> ConfigGuess:
    """Decide which shipped config best fits a paper based on its markdown.

    Heuristics (first match wins within each category):

    * Roman-numeral headers (≥3) → IEEE conference style
    * arXiv ID in body → arXiv preprint
    * Broader-impact / societal-impact language → NeurIPS
    * Very short (<3k words) → IEEE (conference-format bias)
    * Very long (>15k words) → arXiv (preprint bias)
    * Fallback → NeurIPS (the default evalit config)
    """
    roman_hits = len(_IEEE_RE.findall(markdown))
    arxiv_hits = bool(_ARXIV_RE.search(markdown))
    neurips_hits = bool(_NEURIPS_HINTS.search(markdown))
    word_count = len(markdown.split())

    if roman_hits >= 3:
        return ConfigGuess(
            recommended="ieee",
            confidence=min(0.95, 0.5 + 0.05 * roman_hits),
            rationale=f"{roman_hits} Roman-numeral section headers detected (I., II., III., …).",
        )
    if arxiv_hits:
        return ConfigGuess(
            recommended="arxiv",
            confidence=0.85,
            rationale="arXiv ID detected in paper body.",
        )
    if neurips_hits:
        return ConfigGuess(
            recommended="neurips",
            confidence=0.75,
            rationale="Broader-impact / checklist language detected (NeurIPS convention).",
        )
    if word_count < 3000:
        return ConfigGuess(
            recommended="ieee",
            confidence=0.55,
            rationale=f"Short paper ({word_count} words) — matches IEEE conference format.",
        )
    if word_count > 15000:
        return ConfigGuess(
            recommended="arxiv",
            confidence=0.55,
            rationale=f"Long paper ({word_count} words) — matches arXiv preprint norms.",
        )
    return ConfigGuess(
        recommended="neurips",
        confidence=0.50,
        rationale="No strong signal; defaulting to NeurIPS (generic ML venue).",
    )


# ---------------------------------------------------------------------------
# Multi-config pipeline runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigRunResult:
    config_name: str
    record_path: Path
    html_path: Path
    review_md_path: Path
    composite: float
    recommendation: str


def reports_root(home: Path | None = None) -> Path:
    base = home if home is not None else Path.home()
    return base / "evalit-reports"


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip()).strip("-").lower()
    return slug[:60] or "untitled"


def prepare_output_dir(
    paper_slug: str,
    *,
    now: datetime | None = None,
    home: Path | None = None,
) -> Path:
    now = now or datetime.now()
    date = now.strftime("%Y-%m-%d")
    out_dir = reports_root(home) / f"{date}-{paper_slug}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def load_paper(path: Path):
    """Load a paper from either a PDF or a pre-extracted markdown file."""
    if path.suffix.lower() == ".pdf":
        return parse_pdf(path), path.read_text(encoding="utf-8", errors="replace")
    md = path.read_text(encoding="utf-8")
    return parse_markdown(md, source_name=path.stem), md


def run_multi_config(
    paper_path: Path | str,
    config_names: list[str],
    *,
    provider=None,
    http_client: HTTPClient | None = None,
    options: PipelineOptions | None = None,
    home: Path | None = None,
    parallel: bool = True,
) -> tuple[Path, list[ConfigRunResult]]:
    """Run the pipeline against one or more venue configs.

    Returns `(out_dir, results)`. When `len(config_names) > 1`, runs are
    parallel by default (thread pool — each pipeline spends most of its
    time in HTTP + LLM IO, not CPU).
    """
    paper_path = Path(paper_path)
    paper, _markdown = load_paper(paper_path)
    slug = slugify(paper.metadata.title or paper_path.stem)
    out_dir = prepare_output_dir(slug, home=home)

    def _run_one(name: str) -> ConfigRunResult:
        cfg = load_venue_config(config_path(name))
        record = run_pipeline(
            paper,
            cfg,
            provider=provider,
            http_client=http_client,
            options=options or PipelineOptions(),
        )
        record_path = out_dir / f"{name}.json"
        record_path.write_text(dump_record_json(record), encoding="utf-8")
        draft = format_review_draft(record, config=cfg)
        review_path = out_dir / f"{name}.md"
        review_path.write_text(render_review_markdown(draft), encoding="utf-8")
        html_path = out_dir / f"{name}.html"
        html_path.write_text(render_report_html(record), encoding="utf-8")
        return ConfigRunResult(
            config_name=name,
            record_path=record_path,
            html_path=html_path,
            review_md_path=review_path,
            composite=draft.overall_score,
            recommendation=draft.recommendation.value,
        )

    results: list[ConfigRunResult] = []
    if parallel and len(config_names) > 1:
        with ThreadPoolExecutor(max_workers=min(len(config_names), 4)) as pool:
            futures = {pool.submit(_run_one, n): n for n in config_names}
            for fut in as_completed(futures):
                results.append(fut.result())
    else:
        for name in config_names:
            results.append(_run_one(name))

    # Preserve caller's ordering for the comparison table.
    by_name = {r.config_name: r for r in results}
    ordered = [by_name[n] for n in config_names if n in by_name]
    return out_dir, ordered


# ---------------------------------------------------------------------------
# Side-by-side comparison
# ---------------------------------------------------------------------------


def compare_records(record_paths: Sequence[Path | str]) -> str:
    """Render a markdown comparison table across N records.

    Records are loaded from JSON files written by `run_multi_config`.
    """
    rows: list[tuple[str, EvaluationRecord]] = []
    for p in record_paths:
        path = Path(p)
        record = EvaluationRecord.model_validate_json(path.read_text(encoding="utf-8"))
        # Label by parent-directory + file stem, e.g. "ieee" from "ieee.json".
        rows.append((path.stem, record))

    if not rows:
        return "_No records to compare._"

    lines: list[str] = []
    title = rows[0][1].paper.metadata.title
    lines.append(f"# Comparison — {title}")
    lines.append("")

    header = "| Metric |"
    sep = "|---|"
    for name, _ in rows:
        header += f" {name} |"
        sep += "---|"
    lines.append(header)
    lines.append(sep)

    def row(label: str, fn) -> str:
        cells = "".join(f" {fn(r)} |" for _, r in rows)
        return f"| {label} |{cells}"

    lines.append(row("Compliance triage", lambda r: r.compliance.triage.value))
    lines.append(row("Total claims", lambda r: str(r.claims.total_claims)))
    lines.append(row("Hallucinations", lambda r: str(r.claims.hallucination_count)))
    lines.append(
        row(
            "Rubric bias-adjusted",
            lambda r: f"{r.rubric.bias_adjusted_total:.3f}" if r.rubric else "—",
        )
    )
    lines.append(
        row(
            "Composite (recomputed)",
            lambda r: f"{composite_score(r).composite:.3f}",
        )
    )

    def rec(r: EvaluationRecord) -> str:
        return format_review_draft(r).recommendation.value

    lines.append(row("Recommendation", rec))

    # Per-depth row
    lines.append("")
    lines.append("Depth breakdown:")
    lines.append("")
    header2 = "| Dimension |"
    sep2 = "|---|"
    for name, _ in rows:
        header2 += f" {name} |"
        sep2 += "---|"
    lines.append(header2)
    lines.append(sep2)
    for dim in ("methodology", "limitations", "reproducibility", "logical_soundness"):
        cells = ""
        for _, r in rows:
            v = getattr(r.depth, f"{dim}_score") if r.depth else 0.0
            cells += f" {v:.2f} |"
        lines.append(f"| {dim} |{cells}")

    return "\n".join(lines) + "\n"


def write_comparison(out_dir: Path | str, results: list[ConfigRunResult]) -> Path:
    """Write `comparison.md` into `out_dir` for the given run results."""
    out_dir = Path(out_dir)
    paths = [r.record_path for r in results]
    comparison_md = compare_records(paths)
    target = out_dir / "comparison.md"
    target.write_text(comparison_md, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Recompute composite with user-supplied weights
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecomposeResult:
    original_composite: float
    new_composite: float
    delta: float
    recommendation_before: str
    recommendation_after: str
    breakdown: dict[str, float | None]
    weights: dict[str, float]


def recompute_composite(
    record_path: Path | str,
    weights: dict[str, float],
) -> RecomposeResult:
    """Load a saved record and recompute the composite with new weights.

    No pipeline re-run, no LLM calls — purely arithmetic over the saved
    subscore signals. Good for "what-if" exploration.
    """
    record = EvaluationRecord.model_validate_json(Path(record_path).read_text(encoding="utf-8"))
    # Fill in any missing keys with the defaults so partial user input works.
    base = ScoringConfig()
    merged = {**base.weights, **weights}
    cfg = ScoringConfig.model_validate({"weights": merged})

    old = composite_score(record)  # uses defaults
    new = composite_score(record, cfg)

    from evalit_4me.formatters.reviewer import _recommendation_from_total

    return RecomposeResult(
        original_composite=old.composite,
        new_composite=new.composite,
        delta=round(new.composite - old.composite, 4),
        recommendation_before=_recommendation_from_total(old.composite).value,
        recommendation_after=_recommendation_from_total(new.composite).value,
        breakdown=new.breakdown(),
        weights=merged,
    )


def recompute_to_json(result: RecomposeResult) -> str:
    return json.dumps(
        {
            "original_composite": result.original_composite,
            "new_composite": result.new_composite,
            "delta": result.delta,
            "recommendation_before": result.recommendation_before,
            "recommendation_after": result.recommendation_after,
            "breakdown": result.breakdown,
            "weights": result.weights,
        },
        indent=2,
    )
