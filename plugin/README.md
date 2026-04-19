# evalit — Claude Code plugin

Reviewer-assist academic-paper review for Claude Code. Exposes the [evalit-4me](https://github.com/niruta25/evalit-4me) 5-stage pipeline as an MCP server plus a skill that auto-triggers on paper paths and phrases like *"review this paper"*.

**Scope: reviewer-assist, not a reviewer.** Outputs are structured signals for a human reviewer — never an accept/reject decision. Compliance `FAIL` means "a human should look at this first." The composite score is a sort aid, not a threshold. No AI-text detection.

## What you get

- **MCP server** auto-registered on install, exposing four tools:
  - `detect_config(paper_path)` — recommend the best shipped venue config (neurips, ieee, arxiv).
  - `review_paper(paper_path, configs?)` — run the 5-stage pipeline; returns `ReviewDraft` + paths to `review.md`, `report.html`, `record.json`.
  - `reweight(record_path, weights)` — recompute composite with custom weights (no LLM, no network).
  - `compare(record_paths)` — side-by-side markdown comparison of saved records.
- **Skill** (`skills/evalit/SKILL.md`) with playbooks for new-paper, reweight, and compare flows. Triggers on phrases like *"review this paper"*, *"score this submission"*, *"compare under different configs"*.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) on your `PATH`. The MCP server is spawned via `uv run --with "evalit-4me[mcp,pdf] @ git+...@v0.0.1"`, which fetches and caches the Python package automatically — no separate clone or `pip install` required.
- *(Optional)* `ANTHROPIC_API_KEY` exported in the shell where Claude Code runs. The pipeline works without it (heuristic fallback), but rubric scoring is richer with an LLM.
- *(First run)* Expect a one-time download of ~2 GB on first use — this is the `marker-pdf` model weights for PDF parsing. Cached across runs.

## Install

The repo root ships a `marketplace.json` that declares this plugin at `plugin/`. From Claude Code:

```
/plugin marketplace add niruta25/evalit-4me
/plugin install evalit@niruta25-plugins
```

The install pins to release tag `v0.0.1`; upgrades happen when you re-run `/plugin install` after a new tag is cut.

## Example

```
you:    ~/papers/mysubmission.pdf review this
claude: I detected this as most likely an **ieee** paper — structured IMRaD
        sections, double-column layout, IEEE-style numeric citations. Run
        just ieee, or all three configs and compare?
you:    all three
claude: [calls review_paper(..., configs=["neurips","arxiv","ieee"])]
        | config   | composite | recommendation | compliance | unverified refs |
        |----------|-----------|----------------|------------|-----------------|
        | neurips  | 0.68      | WEAK_ACCEPT    | PASS       | 2               |
        | arxiv    | 0.74      | ACCEPT         | PASS       | 2               |
        | ieee     | 0.71      | ACCEPT         | CONDITIONAL| 2               |
        Want me to explain a specific score or tweak the composite weights?
```

## Caveats

- The composite and recommendation are **reviewer-queue signals**, not verdicts. Don't wire them to automated gates.
- Marker-pdf (PDF parser) is heavy. First-run download is ~2 GB.
- Four MCP tools only. For the full CLI (batch processing, fairness audit, Streamlit dashboard), clone [`evalit-4me`](https://github.com/niruta25/evalit-4me) directly.

## Links

- Repo: https://github.com/niruta25/evalit-4me
- Issues: https://github.com/niruta25/evalit-4me/issues
- License: Apache-2.0
