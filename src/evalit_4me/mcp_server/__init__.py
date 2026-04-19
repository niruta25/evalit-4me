"""MCP server surface for Claude Desktop.

Exposes four tools that mirror the Claude Code skill's helpers:

    detect_best_config(paper_path)                -> JSON
    run_multi_config(paper_path, configs)         -> JSON list
    compare_records(record_paths)                 -> markdown
    recompute_composite(record_path, weights)     -> JSON

Install:  the `[mcp]` extra pulls the `mcp` Python SDK; the install.sh
script in `integrations/claude-code-skill/` prints the exact JSON block
to paste into Claude Desktop's config.
"""

from evalit_4me.mcp_server.server import build_server

__all__ = ["build_server"]
