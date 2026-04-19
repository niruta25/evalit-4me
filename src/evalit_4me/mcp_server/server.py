"""MCP stdio server exposing the evalit skill behaviors to Claude Desktop.

**Scope — reviewer assist, not reviewer replacement.** These tools produce
structured artifacts (records, composite scores, verified citations) to
help a human reviewer work faster. They do **not** make accept/reject
decisions and are not calibrated for automated gating. The composite score
is a sort signal; the compliance `FAIL` triage means "look at this first,"
not "auto-reject."

Four tools, all thin wrappers around `evalit_4me.skill_helpers`. Runs as
a stdio process (no ports, no auth — Claude Desktop spawns it as a child
process and talks to it via stdin/stdout).

Run standalone:  `uv run python -m evalit_4me.mcp_server.server`
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from evalit_4me.skill_helpers import (
    SHIPPED_CONFIGS,
    compare_records,
    detect_best_config,
    recompute_composite,
    recompute_to_json,
    run_multi_config,
    write_comparison,
)


def build_server() -> FastMCP:
    """Return a configured `FastMCP` server. Separated for testability."""
    server = FastMCP(name="evalit-4me")

    @server.tool()
    def detect_config(paper_path: str) -> dict[str, Any]:
        """Inspect a paper (PDF or markdown) and recommend the best shipped
        venue config. Returns {recommended, confidence, rationale}.

        `recommended` is one of: neurips, arxiv, ieee.

        Uses the fast `quick_parser` path on PDFs (reads the first few
        pages via pypdf — subsecond) so config detection does not pay
        for a full marker parse.
        """
        path = Path(paper_path).expanduser()
        markdown, full_doc = _quick_sample_markdown(path)
        guess = detect_best_config(markdown, full_doc=full_doc)
        return {
            "recommended": guess.recommended,
            "confidence": round(guess.confidence, 3),
            "rationale": guess.rationale,
        }

    @server.tool()
    def review_paper(
        paper_path: str,
        configs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run the evalit 5-stage pipeline. If `configs` has multiple
        entries, runs are parallel. Writes artifacts to
        ~/evalit-reports/<date>-<slug>/ and returns paths + summary.

        Output is a reviewer-assist draft — composite score and compliance
        triage are sort/triage signals, not accept/reject decisions.

        Arguments:
            paper_path: local filesystem path to a PDF or markdown file.
            configs: list from {"neurips", "arxiv", "ieee"}. Defaults to
                the auto-detected config when omitted.
        """
        path = Path(paper_path).expanduser()
        if not configs:
            # Auto-detect and use just the recommended config. The full
            # marker parse still runs inside run_multi_config; here we
            # only need a fast sniff for the venue heuristic.
            markdown, full_doc = _quick_sample_markdown(path)
            guess = detect_best_config(markdown, full_doc=full_doc)
            configs = [guess.recommended]

        # Validate early so we don't half-run.
        bad = [c for c in configs if c not in SHIPPED_CONFIGS]
        if bad:
            raise ValueError(f"unknown config(s): {bad}; must be one of {SHIPPED_CONFIGS}")

        provider, http_client = _build_runtime()
        out_dir, results = run_multi_config(
            path,
            configs,
            provider=provider,
            http_client=http_client,
            parallel=True,
        )
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


def _quick_sample_markdown(path: Path) -> tuple[str, bool]:
    """Return `(text, full_doc)` for venue-detection purposes.

    - `.pdf`: first few pages via pypdf (`full_doc=False` — `detect_best_config`
      skips length heuristics on partial input).
    - `.md` or anything else: the whole file (`full_doc=True`).
    """
    if path.suffix.lower() == ".pdf":
        from evalit_4me.ingest.quick_parser import quick_extract_first_pages

        return quick_extract_first_pages(path), False
    return path.read_text(encoding="utf-8"), True


def _build_runtime():
    """Return `(provider, http_client)` using env vars when present."""
    provider = None
    http_client = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        from evalit_4me.llm.anthropic_adapter import AnthropicProvider
        from evalit_4me.llm.cache import CachingProvider, DiskCache
        from evalit_4me.llm.cost import CostTracker

        provider = CachingProvider(
            inner=AnthropicProvider(),
            cache=DiskCache(),
            tracker=CostTracker(),
        )
    from evalit_4me.stages.verify import HTTPClient

    http_client = HTTPClient()
    return provider, http_client


def main() -> None:  # pragma: no cover — stdio entrypoint
    server = build_server()
    server.run()


if __name__ == "__main__":  # pragma: no cover
    main()
