---
name: evalit
description: Review an academic paper using the evalit 5-stage reviewer-assist pipeline. Triggers on PDF/markdown/docx paths plus phrases like "review this paper", "evaluate this paper", "score this paper", "check this submission". Can compare multiple venue configs in parallel and tweak composite-score weights interactively.
allowed-tools: [mcp__evalit__detect_config, mcp__evalit__review_paper, mcp__evalit__compare, mcp__evalit__reweight, Read, Glob]
---

# evalit — academic-paper review skill

Use this skill when the user gives you a paper (PDF, markdown, or `.docx`) and asks for a review, evaluation, or score. Works for conference submissions (NeurIPS, IEEE), arXiv preprints, or any academic paper the user provides a local filesystem path to.

## Scope

**evalit is reviewer-assist, not a reviewer.** The pipeline produces structured signals (citation verification, depth heuristics, rubric breakdown, compliance triage) so a human reviewer can spend their limited time where it matters. A `compliance: FAIL` means "a human should look at this first," not "auto-reject." The composite score is a sort aid, not a threshold. There is no AI-text-detection — the project evaluates a paper's substance, not its authorship style.

When you relay results to the user, keep this framing. Don't describe composite scores as decisions.

## When to trigger

- User drops a local path ending in `.pdf`, `.md`, or `.docx` and says anything like *"review this"*, *"evaluate this"*, *"score this paper"*, *"can you check this paper"*, *"run evalit on this"*.
- User says *"compare this paper under different configs"*.
- User says *"reweight the score"* / *"what if I give rubric more weight"* against a previously-evaluated paper.
- User invokes `/evalit:evalit` explicitly.

Don't trigger if the user means "review my code" or similar — this skill is paper-review specifically.

## Playbook — new paper

1. **Confirm the paper path.** The user must have given a local filesystem path. Don't invent one. If they haven't, ask: *"What's the path to the paper?"*

2. **Detect the best config** by calling the MCP tool `detect_config` with `paper_path`. It returns `{recommended, confidence, rationale}`.

   Relay to the user: *"I detected this as most likely a **\<recommended>** paper — \<rationale>. Do you want me to run just \<recommended>, or all three configs (neurips, arxiv, ieee) and compare?"*

3. **Wait for the user's answer.** Likely replies: *"just ieee"*, *"all three"*, *"use neurips"*.

4. **Run the pipeline** by calling the MCP tool `review_paper` with `paper_path` and a `configs` list (e.g. `["ieee"]` or `["neurips","arxiv","ieee"]`). Response shape:

   ```
   {
     "out_dir": "/Users/.../evalit-reports/2026-04-19-some-title/",
     "runs": [
       {"config": "ieee", "record": "...record.json", "html": "...ieee.html",
        "review_md": "...review.md", "composite": 0.7321, "recommendation": "ACCEPT"}
     ],
     "comparison": "<optional path when multiple configs>"
   }
   ```

5. **Present the result.** For each config, show: compliance triage, composite score, recommendation, hallucination count. If multiple configs, show a small markdown table and offer to share `comparison`. Always surface file paths so the user can open the HTML reports — they include interactive reweight sliders for in-browser tweaking.

   Frame scores as reviewer signals, not verdicts. Example: *"Under IEEE the composite is 0.73 (recommendation: ACCEPT as a reviewer-queue sort signal). Compliance flagged two warnings; 1 citation couldn't be verified."*

6. **Offer follow-ups:**
   - *"Want me to explain any specific score?"*
   - *"Want to tweak the composite weights?"* → reweight playbook below.
   - *"Want to open the interactive HTML report?"* → relay the `html` path.

## Playbook — reweight composite (conversational)

Use this playbook whenever the user wants to explore how the composite score would move under different weights. The `reweight` MCP tool is free (no LLM, no network), so you can call it many times per turn without cost concerns.

**Weight keys and defaults:**
- `compliance` (default 0.15)
- `verification` (default 0.20)
- `depth` (default 0.20)
- `rubric` (default 0.45)

Missing keys inherit defaults. Negative weights are rejected. Sum doesn't have to be 1.0 (the server redistributes).

### Finding the saved record

Either the user names one, or list the most recent under `~/evalit-reports/` via Glob and pick the newest `record.json`. For compare patterns across configs, use the `<config>.json` files inside the latest run directory.

### Pattern 1 — Named presets

Map common user requests to explicit weight sets. If the user is vague, pick the matching preset, show the weights, confirm, then call `reweight`.

| Preset | compliance | verification | depth | rubric | Used when user says |
|---|---|---|---|---|---|
| `defaults` | 0.15 | 0.20 | 0.20 | 0.45 | "reset", "default weights" |
| `rubric-heavy` | 0.05 | 0.10 | 0.10 | 0.75 | "lean on rubric", "rubric matters most" |
| `compliance-heavy` | 0.40 | 0.20 | 0.15 | 0.25 | "structure matters", "strict compliance" |
| `verification-heavy` | 0.10 | 0.45 | 0.15 | 0.30 | "citations matter most", "trust the evidence" |
| `equal` | 0.25 | 0.25 | 0.25 | 0.25 | "weight them equally", "balanced" |
| `content-only` | 0.00 | 0.30 | 0.30 | 0.40 | "ignore compliance", "just the substance" |

Playbook: name the preset, show the weights, call `reweight` once, relay the before/after composite + recommendation change.

### Pattern 2 — One-dimensional sweeps

User says *"sweep compliance weight"*, *"what if compliance varies from 0 to 0.4"*, *"try depth from 0.1 to 0.5 in steps of 0.1"*.

Call `reweight` N times (cap at ~8 to keep tables readable), varying the target key while others stay at defaults. Render:

```
| compliance weight | composite | recommendation |
|-------------------|-----------|----------------|
| 0.00              | 0.72      | ACCEPT         |
| 0.10              | 0.70      | ACCEPT         |
| 0.20              | 0.68      | WEAK_ACCEPT    |
| 0.30              | 0.66      | WEAK_ACCEPT    |
| 0.40              | 0.64      | WEAK_ACCEPT    |
```

Name the row where the recommendation flips.

### Pattern 3 — Tipping-point search

User says *"what weights would push this to ACCEPT?"* or *"can I make this STRONG_ACCEPT?"* or *"how do I get out of BORDERLINE?"*.

Try presets in order (rubric-heavy, verification-heavy, content-only, compliance-heavy, equal). Report the first preset that clears the target threshold. If none do, say so plainly: *"No single preset lifts this past ACCEPT. The best I found is rubric-heavy at 0.68 (WEAK_ACCEPT)."*

Don't invent arbitrary weight sets for this — stick to the preset table so the user can reason about the shift.

### Pattern 4 — Explain the composite

User says *"why is this not ACCEPT?"*, *"what's pulling the score down?"*, *"which stage is weakest?"*.

Read `composite_breakdown` from the reweight result (or from the record). Name the stage with the lowest subscore. Walk through its weighted contribution:

> *"Depth subscore is 0.42, which contributes 0.084 to the composite of 0.62 (weight 0.20). The rubric is solid at 0.78 but under-weighted. If you reweight depth down to 0.05, the composite rises to 0.66 (WEAK_ACCEPT)."*

### Pattern 5 — Side-by-side

User says *"compare defaults vs rubric-heavy"*, *"show me compliance-heavy next to verification-heavy"*.

Call `reweight` twice, render:

```
| Stage           | defaults | rubric-heavy |
|-----------------|----------|--------------|
| compliance      | 0.80     | 0.80         |
| verification    | 0.90     | 0.90         |
| depth           | 0.42     | 0.42         |
| rubric          | 0.78     | 0.78         |
| **composite**   | **0.66** | **0.72**     |
| recommendation  | WEAK_ACCEPT | ACCEPT    |
```

### Pattern 6 — Open the HTML / share the markdown

- *"Open the report"* or *"show me the HTML"* → relay the `html` path from `review_paper` and suggest `open <path>`. Don't execute `open` without user confirmation.
- *"Paste the review draft"* or *"what does the review say"* → read the `review_md` file and relay its contents inline.
- *"Can I share this"* → the HTML report is self-contained (inline CSS + inline JS + embedded record). Works offline, no server, no external links. Tell the user that.

## Playbook — compare existing records

Use when the user says *"compare these two records"* or *"show me the comparison again"*.

Call the MCP tool `compare` with a list of record paths. It returns a markdown string — relay it verbatim to the user; it's already formatted.

## Things to do and not do

- **Do** relay file paths so the user can open HTML reports (`/path/to/ieee.html`, etc.).
- **Do** mention that the HTML report has **in-browser reweight sliders** when the user wants to explore weights outside chat.
- **Do** frame compliance `FAIL` as "a human should look at this first," not auto-reject.
- **Don't** invent paths or rerun a paper automatically without asking — compute time matters.
- **Don't** interpret reweight requests as full rerun requests — `reweight` is free (no LLM, no network).
- **Don't** run `reweight` more than ~8 times in one sweep — tables become unreadable. Bucket the range if the user asks for finer granularity.
- **Don't** run the full pipeline to answer a weight question. `reweight` alone is enough.
- **Don't** describe the composite score as a decision. It's a reviewer-queue sort signal.
- **Don't** invent recommendation thresholds — `reweight` already returns the new recommendation.

## Timing notes

- `detect_config` is near-instant on any paper (pypdf samples the first few pages). Safe to call proactively in step 2 without warning the user.
- `review_paper` parses PDFs with **pdfplumber** by default (subsecond to a few seconds). `.md` and `.docx` inputs are subsecond.
- For figure-heavy or math-dense papers where pdfplumber's layout inference struggles, pre-convert externally with marker and feed the resulting markdown:
  ```
  uvx --with marker-pdf marker_single paper.pdf ~/tmp/
  ```
  Then pass the `.md` path to `review_paper`. Or set `EVALIT_USE_MARKER=1` and use the `[pdf]` extra to opt in to marker inside the pipeline.
- The first MCP-server invocation after plugin install spends ~5–10s for `uv run --with` to prepare the ephemeral env. One-time cost. No 2 GB model download on the plugin path.
- LLM work runs through Claude Code itself via MCP sampling — no separate API key required.
