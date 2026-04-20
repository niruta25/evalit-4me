# evalit — Claude Code plugin

Reviewer-assist academic-paper review for Claude Code. Exposes the [evalit-4me](https://github.com/niruta25/evalit-4me) 5-stage pipeline as an MCP server plus a skill that auto-triggers on paper paths and phrases like *"review this paper"*.

**Scope: reviewer-assist, not a reviewer.** Outputs are structured signals for a human reviewer — never an accept/reject decision. Compliance `FAIL` means "a human should look at this first." The composite score is a sort aid, not a threshold. No AI-text detection.

## What you get

- **MCP server** auto-registered on install, exposing four tools:
  - `detect_config(paper_path)` — recommend the best shipped venue config (neurips, ieee, arxiv).
  - `review_paper(paper_path, configs?)` — run the 5-stage pipeline; returns `ReviewDraft` + paths to `review.md`, `report.html`, `record.json`.
  - `reweight(record_path, weights)` — recompute composite with custom weights (no LLM, no network).
  - `compare(record_paths)` — side-by-side markdown comparison of saved records.
- **Skill** (`skills/evalit/SKILL.md`) with playbooks for new-paper, reweight (six conversational patterns: presets, sweeps, tipping-point search, explain, side-by-side, share), and compare flows.
- **Interactive HTML report** (`<config>.html`) with in-browser reweight sliders — drag to recompute composite + recommendation live. Shareable, offline, no server.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) on your `PATH`. The MCP server is spawned via `uv run --with "evalit-4me[mcp,pdf-lite,docx] @ git+...@v0.0.3"`, which fetches and caches the Python package automatically — no separate clone or `pip install` required. Cold-start is ~5–10s; subsequent invocations are instant.
- **No API key required.** LLM work (rubric scoring, citation entailment) runs through Claude Code via MCP sampling using whatever model auth Claude Code already has. If the host client doesn't support sampling, the pipeline falls back to its deterministic heuristic mode — you still get a full result.
- **Inputs accepted:** `.pdf`, `.md`, `.docx`. PDFs are parsed with `pdfplumber` (~10 MB, subsecond on most papers). For figure-heavy or math-dense PDFs where pdfplumber struggles, pre-convert with marker externally and feed the `.md`, or set `EVALIT_USE_MARKER=1` to opt in to marker inside the pipeline (requires the `[pdf]` extra and ~2 GB of model weights).

## Install

The repo root ships a `.claude-plugin/marketplace.json` that declares this plugin at `plugin/`. From Claude Code:

```
/plugin marketplace add niruta25/evalit-4me
/plugin install evalit@niruta25-plugins
```

The install pins to release tag `v0.0.3`; upgrades happen when you re-run `/plugin install` after a new tag is cut.

## Try it

Eight sample papers live in [`plugin/examples/`](./examples/) — one per venue style, a compliance-FAIL case, a fabricated-citation case, plus PDF and DOCX variants. Fastest smoke test:

```
you:    review this paper at plugin/examples/sample_neurips.md
claude: [detects neurips, runs pipeline in seconds, shows composite + recommendation]
```

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
you:    what if I lean on rubric?
claude: [calls reweight(..., {"rubric": 0.75, "compliance": 0.05, ...})]
        rubric-heavy preset lifts neurips from 0.68 → 0.74 (ACCEPT). The
        HTML report at /Users/.../evalit-reports/.../neurips.html also has
        sliders if you want to keep tweaking in a browser.
```

## Caveats

- The composite and recommendation are **reviewer-queue signals**, not verdicts. Don't wire them to automated gates.
- pdfplumber is "good enough" for most LaTeX-generated PDFs (single and two-column). Math-heavy or figure-dense layouts may lose fidelity — use the marker opt-in path in that case.
- `marker-pdf`, when enabled, is GPLv3 and pulls ~2 GB of model weights on first use. Kept out of the plugin default install for this reason.
- Four MCP tools only. For the full CLI (batch processing, fairness audit), clone [`evalit-4me`](https://github.com/niruta25/evalit-4me) directly.

## Links

- Repo: https://github.com/niruta25/evalit-4me
- Issues: https://github.com/niruta25/evalit-4me/issues
- License: Apache-2.0
