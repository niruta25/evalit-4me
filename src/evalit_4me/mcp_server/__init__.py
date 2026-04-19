"""MCP server surface for Claude Desktop and the Claude Code plugin.

Exposes four reviewer-assist tools:

    detect_config(paper_path)                     -> JSON
    review_paper(paper_path, configs=None)        -> JSON
    compare(record_paths)                         -> markdown
    reweight(record_path, weights)                -> JSON

Install:  the `[mcp]` extra pulls the `mcp` Python SDK. The Claude Code
plugin at `plugin/` auto-registers this server via `.mcp.json`; for
Claude Desktop, add the equivalent block to `claude_desktop_config.json`
under `mcpServers`.
"""

from evalit_4me.mcp_server.server import build_server

__all__ = ["build_server"]
