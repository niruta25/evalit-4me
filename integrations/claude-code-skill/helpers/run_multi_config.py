#!/usr/bin/env python3
"""Run the evalit pipeline against one or more venue configs in parallel.

usage:  run_multi_config.py <paper.pdf> <config1>[,<config2>,...] [--no-llm] [--no-http]

Writes artifacts to ~/evalit-reports/<YYYY-MM-DD>-<slug>/:
  <config>.json, <config>.html, <config>.md
  comparison.md (only when N > 1)

Prints one JSON line per completed run:
  {"config": "ieee", "record": ".../ieee.json", "composite": 0.38, "recommendation": "WEAK_REJECT", "html": ".../ieee.html"}

Followed by a final "summary" line pointing at the out_dir + comparison.md if present.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 2:
        print(
            "usage: run_multi_config.py <paper> <config1[,config2,...]> [--no-llm] [--no-http]",
            file=sys.stderr,
        )
        return 2

    paper_path = Path(args[0])
    config_names = [c.strip() for c in args[1].split(",") if c.strip()]
    flags = set(args[2:])

    use_llm = "--no-llm" not in flags
    use_http = "--no-http" not in flags

    from evalit_4me.skill_helpers import run_multi_config, write_comparison

    provider = None
    http_client = None
    if use_llm and os.environ.get("ANTHROPIC_API_KEY"):
        from evalit_4me.llm.anthropic_adapter import AnthropicProvider
        from evalit_4me.llm.cache import CachingProvider, DiskCache
        from evalit_4me.llm.cost import CostTracker

        provider = CachingProvider(
            inner=AnthropicProvider(),
            cache=DiskCache(),
            tracker=CostTracker(),
        )
    if use_http:
        from evalit_4me.stages.verify import HTTPClient

        http_client = HTTPClient()

    out_dir, results = run_multi_config(
        paper_path,
        config_names,
        provider=provider,
        http_client=http_client,
        parallel=True,
    )

    for r in results:
        print(
            json.dumps(
                {
                    "config": r.config_name,
                    "record": str(r.record_path),
                    "html": str(r.html_path),
                    "review_md": str(r.review_md_path),
                    "composite": round(r.composite, 4),
                    "recommendation": r.recommendation,
                }
            )
        )

    summary: dict[str, object] = {
        "out_dir": str(out_dir),
        "config_count": len(results),
    }
    if len(results) > 1:
        comparison = write_comparison(out_dir, results)
        summary["comparison"] = str(comparison)
    print(json.dumps({"summary": summary}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
