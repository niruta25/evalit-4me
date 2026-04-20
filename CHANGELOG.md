# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.3] - 2026-04-19

### Changed
- **Plugin MCP server no longer requires `ANTHROPIC_API_KEY`.** LLM calls now route through the host client via MCP `sampling/createMessage`. When the client doesn't support sampling, the pipeline falls back to deterministic heuristic mode — users still get a full result with no setup. The direct-API path (`AnthropicProvider`) remains available for CLI users running outside Claude Code.
- **PDF parsing default is now `pdfplumber`**, not `marker-pdf`. Install size on the plugin path drops from ~2 GB to ~10 MB. Two escape hatches for higher-fidelity parsing on figure- or math-heavy PDFs: set `EVALIT_USE_MARKER=1` in the environment, or pass `--full-fidelity` to `evalit review`. Marker is installed via the existing `[pdf]` extra; the plugin default now pulls `[pdf-lite]` instead.
- `plugin/.mcp.json` spawn line: `evalit-4me[mcp,pdf]` → `evalit-4me[mcp,pdf-lite,docx]`.
- `plugin/skills/evalit/SKILL.md` reweight playbook expanded with six conversational patterns: named presets, one-dim sweeps, tipping-point search, composite explanation, side-by-side comparison, and open-HTML / copy-markdown.

### Added
- `.docx` input support via `mammoth` (new `[docx]` optional extra, ~2 MB).
- `src/evalit_4me/ingest/plumber_parser.py` — pdfplumber-backed PDF parser.
- `src/evalit_4me/ingest/docx_parser.py` — mammoth-backed `.docx` parser.
- `src/evalit_4me/ingest/dispatch.py` — unified `load_paper(path, use_marker=...)` dispatcher honoring the `EVALIT_USE_MARKER` env var.
- `src/evalit_4me/llm/mcp_sampling_adapter.py` — `McpSamplingProvider` wrapping `ctx.session.create_message` with a sync-over-async bridge for the existing synchronous pipeline. Detects and raises `SamplingUnsupportedError` when the client cannot sample.
- **Interactive HTML report**: `formatters/html.py` now embeds the record JSON and four range sliders (`compliance`, `verification`, `depth`, `rubric`). JS recomputes the composite in-browser using the same formula as `recompute_composite`. Includes reset-to-defaults and copy-review-markdown buttons.
- `plugin/examples/` — 8 sample papers (5 `.md`, 2 `.pdf`, 1 `.docx`) covering NeurIPS / IEEE / arXiv happy paths, a compliance-FAIL case, a fabricated-citation case, single- and two-column PDFs, and the `.docx` dispatcher. Plus a short `plugin/examples/README.md` mapping each sample to the signal it exercises.
- `scripts/regenerate_samples.sh` + `scripts/regenerate_samples.py` for rebuilding the PDF/DOCX samples from the markdown sources.
- `--full-fidelity` flag on `evalit review` to opt into marker-pdf parsing.
- `tests/unit/test_mcp_sampling_adapter.py` — unit tests for the sampling adapter, including the sync-over-async thread bridge.
- `src/evalit_4me/formatters/sections.py` — pure section-builder (`ViewSection`, `build_view_sections`) moved out of the old dashboard module so HTML can consume it without a Streamlit import.

### Removed
- **Streamlit dashboard** deleted: `src/evalit_4me/dashboard/`, `[dashboard]` optional extra, `evalit dashboard` CLI command, `tests/unit/test_dashboard.py`. The interactive HTML report with in-browser sliders replaces every use case the dashboard served.
- `ANTHROPIC_API_KEY` usage from the MCP server (`_build_runtime` deleted).

## [0.0.2] - 2026-04-19

### Added
- `src/evalit_4me/ingest/quick_parser.py`: pypdf-backed `quick_extract_first_pages(path, n=3)` — subsecond partial-PDF text extractor used exclusively for venue-config detection. No model weights, no subprocess.
- `pypdf>=5.0` added to the `[pdf]` optional extra alongside `marker-pdf`.

### Changed
- `detect_config` MCP tool now uses the quick parser on PDFs. Previously it called the full `marker_single` pipeline just to sniff the venue, which could take 5–10 minutes and occasionally time out (observed: a complex PDF hitting the 600s `MarkerRunner` limit and stalling config detection entirely). Detection is now near-instant regardless of document size.
- `review_paper` MCP tool: same change for the auto-detect code path (when the caller omits `configs`). The full marker parse still runs inside `run_multi_config`; only the venue sniff is now cheap.
- `skill_helpers.detect_best_config(markdown, *, full_doc=True)` — new `full_doc` kwarg. When `False` (the quick-parser callers pass this), length-based heuristics (`<3k` / `>15k` word-count bins) are skipped because they are not meaningful on a sample. Strong signals (Roman-numeral headers, arXiv IDs, broader-impact language) still match. Backwards compatible.
- Plugin SKILL.md rewrote the "First-run note" as "Timing notes" to reflect the new two-tier cost model (detect is free; full PDF parse still takes minutes). Also documents the `uvx` pre-convert escape hatch for users who plan to iterate.
- `plugin/.mcp.json` pin bumped `@v0.0.1` → `@v0.0.2`; Claude Desktop snippet in the root README bumped to match.
- `pyproject.toml` version 0.0.1 → 0.0.2; `http_client.py` default user-agent updated to match.

### Fixed
- Marketplace manifest location: moved `marketplace.json` to `.claude-plugin/marketplace.json` at repo root. Claude Code's `/plugin marketplace add` looks for the manifest under `.claude-plugin/` — the bare-root location fails with "Marketplace file not found." README references updated.
- Marketplace manifest `source` schema: changed from invalid `{"source": "git-subdir", "path": "plugin"}` (missing `url` for cross-repo subdir) to the simple relative-path string `"./plugin"` that same-repo subdir plugins use. Also added `$schema`, `description`, `category`, and per-plugin `homepage` fields to match the format used by the official claude-plugins marketplace.

### Added
- `marketplace.json` at repo root: declares the `evalit` plugin at `plugin/` as a `git-subdir` source, so `/plugin marketplace add niruta25/evalit-4me` + `/plugin install evalit@niruta25-plugins` resolves correctly.
- New `[pdf]` optional extra in `pyproject.toml` for `marker-pdf`.

### Changed
- `marker-pdf` moved from base `dependencies` to the new `[pdf]` optional extra. Core install is now lean (no 2 GB ML weights for users who only review pre-extracted markdown). The plugin's `.mcp.json` requests `evalit-4me[mcp,pdf]` so PDF review still works out of the box.
- `plugin/.mcp.json` pins the git dependency to release tag `@v0.0.1` (was: unpinned `main`). Reproducible across spawns; no surprise drift.
- `plugin/skills/evalit/SKILL.md` `allowed-tools` tightened — removed `Bash` and `Write` (unused). Skill only needs the four `mcp__evalit__*` tools plus `Read` and `Glob`.
- README install docs updated: `uv sync --extra pdf` for PDF support; plugin install uses the new marketplace flow; Claude Desktop snippet pinned to `@v0.0.1` with `[mcp,pdf]`.

### Removed
- `plugin/commands/evalit.md` — redundant with the skill, which already auto-triggers on paper paths and invocation phrases. Removes duplicated playbook guidance.

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

[Unreleased]: https://github.com/niruta25/evalit-4me/compare/v0.0.3...HEAD
[0.0.3]: https://github.com/niruta25/evalit-4me/releases/tag/v0.0.3
[0.0.2]: https://github.com/niruta25/evalit-4me/releases/tag/v0.0.2
[0.0.1]: https://github.com/niruta25/evalit-4me/releases/tag/v0.0.1
