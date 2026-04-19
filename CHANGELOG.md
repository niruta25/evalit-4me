# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Claude Code plugin at `plugin/` — `.claude-plugin/plugin.json` manifest, `.mcp.json` for auto-registered MCP server, `skills/evalit/SKILL.md`, `commands/evalit.md`, and `plugin/README.md`. Install via `/plugin install evalit@niruta25/evalit-4me`; no more manual `claude_desktop_config.json` edits or `install.sh`.
- README "Scope & responsible use" section: explicit reviewer-assist framing, no AI-text detection, composite score is a sort aid not a threshold.
- Docstring on `Triage` enum clarifying `FAIL` is a reviewer triage signal, never auto-reject.
- Responsible-use notes in MCP server module docstring and `review_paper` tool description so Claude Desktop users see the framing.

### Changed
- Claude Code install flow: `/plugin install ...` replaces the old `bash integrations/claude-code-skill/install.sh` + manual JSON-paste. Claude Desktop still supports the config-paste path and the example has been updated to use `uv run --with` (no repo clone required).

### Removed
- `integrations/claude-code-skill/` directory — replaced by the plugin at `plugin/`. The helper CLI wrappers in `integrations/claude-code-skill/helpers/` are gone; the same behaviors are available as MCP tools (`detect_config`, `review_paper`, `compare`, `reweight`).

## [0.0.1] - 2026-04-18

### Added
- Initial 5-stage evaluation pipeline: ingest, compliance, citation verification, depth assessment, rubric scoring.
- Contract-first Pydantic models in `src/evalit_4me/contracts.py`.
- Provider-agnostic LLM protocol (`src/evalit_4me/llm/protocol.py`).
- Venue configs: NeurIPS, IEEE, arXiv (`configs/`).
- CLI entry point, Python API, Streamlit dashboard.
- Claude Code skill (`integrations/claude-code-skill/`) and Claude Desktop MCP server.
- CI via GitHub Actions (ruff, pyright, pytest on Python 3.11 & 3.12).
- Pre-commit hooks (ruff, pyright, large-file guard).

[Unreleased]: https://github.com/niruta25/evalit-4me/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/niruta25/evalit-4me/releases/tag/v0.0.1
