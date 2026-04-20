"""MCP stdio server exposing evalit's reviewer-assist pipeline.

**Scope — reviewer assist, not reviewer replacement.** These tools produce
structured artifacts (records, composite scores, verified citations) to
help a human reviewer work faster. They do **not** make accept/reject
decisions and are not calibrated for automated gating.

Four tools, all thin wrappers around `evalit_4me.skill_helpers`. Runs as
a stdio process — Claude Code spawns it as a child process and talks to
it via stdin/stdout.

**LLM auth:** the server never reads `ANTHROPIC_API_KEY`. When rubric
scoring or claim entailment needs an LLM call, the server asks the MCP
client (Claude Code) to run the completion via `sampling/createMessage`.
Clients that don't support sampling still get a useful result: the
pipeline falls back to its deterministic heuristic mode.

Run standalone: `uv run python -m evalit_4me.mcp_server.server`
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from evalit_4me.llm.cache import CachingProvider, DiskCache
from evalit_4me.llm.cost import CostTracker
from evalit_4me.llm.mcp_sampling_adapter import (
    McpSamplingProvider,
    SamplingUnsupportedError,
)
from evalit_4me.skill_helpers import (
    SHIPPED_CONFIGS,
    compare_records,
    detect_best_config,
    recompute_composite,
    recompute_to_json,
    run_multi_config,
    write_comparison,
)
from evalit_4me.stages.verify import HTTPClient

log = logging.getLogger("evalit.mcp")


def build_server() -> FastMCP:
    """Return a configured `FastMCP` server. Separated for testability."""
    server = FastMCP(name="evalit-4me")

    @server.tool()
    def detect_config(paper_path: str) -> dict[str, Any]:
        """Inspect a paper (PDF, markdown, or .docx) and recommend the best
        shipped venue config. Returns {recommended, confidence, rationale}.

        `recommended` is one of: neurips, arxiv, ieee.

        For PDFs this uses `quick_parser` (pypdf, first few pages, subsecond).
        `.md` and `.docx` inputs are read in full.
        """
        path = Path(paper_path).expanduser()
        markdown, full_doc = _quick_sample_text(path)
        guess = detect_best_config(markdown, full_doc=full_doc)
        return {
            "recommended": guess.recommended,
            "confidence": round(guess.confidence, 3),
            "rationale": guess.rationale,
        }

    @server.tool()
    async def review_paper(
        paper_path: str,
        configs: list[str] | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Run the evalit 5-stage pipeline. If `configs` has multiple
        entries, runs are parallel. Writes artifacts to
        ~/evalit-reports/<date>-<slug>/ and returns paths + summary.

        Output is a reviewer-assist draft — composite score and compliance
        triage are sort/triage signals, not accept/reject decisions.

        Arguments:
            paper_path: local filesystem path to a `.pdf`, `.md`, or `.docx`.
            configs: list from {"neurips", "arxiv", "ieee"}. Defaults to
                the auto-detected config when omitted.
        """
        path = Path(paper_path).expanduser()
        if not configs:
            markdown, full_doc = _quick_sample_text(path)
            guess = detect_best_config(markdown, full_doc=full_doc)
            configs = [guess.recommended]

        bad = [c for c in configs if c not in SHIPPED_CONFIGS]
        if bad:
            raise ValueError(f"unknown config(s): {bad}; must be one of {SHIPPED_CONFIGS}")

        loop = asyncio.get_running_loop()
        provider = _build_sampling_provider(ctx, loop=loop)
        http_client = HTTPClient()

        # Pipeline is sync — we run it in a worker thread below so the MCP
        # event loop stays free for sampling round-trips.

        def _run() -> tuple[Path, list[Any]]:
            try:
                return run_multi_config(
                    path,
                    configs,
                    provider=provider,
                    http_client=http_client,
                    parallel=True,
                )
            except SamplingUnsupportedError:
                log.info(
                    "MCP client does not support sampling; re-running pipeline "
                    "in heuristic mode (no LLM)."
                )
                return run_multi_config(
                    path,
                    configs,
                    provider=None,
                    http_client=http_client,
                    parallel=True,
                )

        out_dir, results = await asyncio.to_thread(_run)

        payload: dict[str, Any] = {
            "out_dir": str(out_dir),
            "runs": [
                {
                    "config": r.config_name,
                    "record": str(r.record_path),
                    "html": str(r.html_path),
                    "review_md": str(r.review_md_path),
                    "composite": round(r.composite, 4),
                    "recommendation": r.recommendation,
                }
                for r in results
            ],
        }
        if len(results) > 1:
            payload["comparison"] = str(write_comparison(out_dir, results))
        return payload

    @server.tool()
    def compare(record_paths: list[str]) -> str:
        """Produce a side-by-side markdown comparison of saved records."""
        return compare_records(record_paths)

    @server.tool()
    def reweight(record_path: str, weights: dict[str, float]) -> dict[str, Any]:
        """Recompute the composite score for a saved record with custom weights.

        No LLM calls, no network. Returns before/after composite, new
        recommendation, and the per-stage breakdown.

        Weight keys: compliance, verification, depth, rubric. Missing keys
        inherit the default (0.15 / 0.20 / 0.20 / 0.45).
        """
        result = recompute_composite(record_path, weights)
        return json.loads(recompute_to_json(result))

    return server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _quick_sample_text(path: Path) -> tuple[str, bool]:
    """Return `(text, full_doc)` for venue-detection purposes.

    - `.pdf`: first few pages via pypdf (`full_doc=False`).
    - `.docx`: full mammoth markdown (`full_doc=True`).
    - `.md`/`.txt`/anything else: read as text (`full_doc=True`).
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from evalit_4me.ingest.quick_parser import quick_extract_first_pages

        return quick_extract_first_pages(path), False
    if suffix == ".docx":
        try:
            import mammoth
        except ImportError:
            # Docx extra not installed — detection still works from the
            # filename + a soft fallback to "no hints".
            return "", True
        with path.open("rb") as fh:
            result = mammoth.convert_to_markdown(fh)
        return result.value or "", True
    return path.read_text(encoding="utf-8"), True


def _build_sampling_provider(
    ctx: Context | None,
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> CachingProvider | None:
    """Wrap MCP sampling in the caching + cost-tracking provider layers.

    Returns None when no `Context` is available (e.g. a unit test invoking
    the tool directly). The pipeline then runs in heuristic mode.
    """
    if ctx is None:
        return None
    try:
        inner = McpSamplingProvider(ctx=ctx, loop=loop)
    except Exception:
        log.exception("Failed to construct McpSamplingProvider; falling back to heuristic mode.")
        return None
    return CachingProvider(
        inner=inner,
        cache=DiskCache(),
        tracker=CostTracker(),
    )


def main() -> None:  # pragma: no cover — stdio entrypoint
    server = build_server()
    server.run()


if __name__ == "__main__":  # pragma: no cover
    main()
