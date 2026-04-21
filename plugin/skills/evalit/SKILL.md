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

**Every paper-review response MUST include all three of:**

1. The **reviewer-assist banner** at the top (see "Output template" below).
2. **Per-stage subscores with rationales pulled from `record.json`** — not just the composite. Quote `rubric.dimensions[].rationale`, `depth.rationales`, `compliance.issues[]`, and per-claim `VerificationResult.notes` verbatim; never paraphrase or invent a rationale.
3. The **verify footer** at the bottom reminding the user to cross-check every claim against the paper itself.

A composite number with no per-stage breakdown is not an acceptable output. A recommendation without the "not a verdict" hedge is not an acceptable output.

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

5. **Read `record.json` before writing the response.** The MCP response only carries `composite` and `recommendation`. The justification lives inside the record file — `Read` it with the `Read` tool so you can quote:
   - `compliance.triage`, `compliance.issues[]`, `compliance.section_checks[]`
   - `claims.total_claims`, `verified_count`, `hallucination_count`, and each `results[].notes` / `evidence` / `source` / `confidence`
   - `depth.methodology_score`, `limitations_score`, `reproducibility_score`, `logical_soundness_score`, and the matching keys in `depth.rationales`
   - `rubric.dimensions[]` — every dimension's `name`, `score`, `max_score`, `rationale`
   - `extra.composite_breakdown` (per-stage subscores as floats in [0,1])

6. **Present the result using the "Output template" below.** Non-negotiable elements: reviewer-assist banner, at-a-glance table, per-stage bar breakdown with rationales, rubric dimension table, unverified/hallucinated-claims list (even when empty), recommendation with hedge, verify footer, file paths.

   For multi-config runs, lead with the at-a-glance comparison table; then offer to drill into one config using the full template.

7. **Offer follow-ups:**
   - *"Want me to explain any specific subscore in more depth?"*
   - *"Want to tweak the composite weights?"* → reweight playbook below.
   - *"Want to open the interactive HTML report?"* → relay the `html` path. Mention it has in-browser reweight sliders.

## Output template — standardized report

Use this template whenever you present `review_paper` results. Sections marked **required** must appear every time, in this order. The body pulls from `record.json`; keep score-to-rationale pairings tight so a reviewer can scan in under 30 seconds.

### 1. Reviewer-assist banner (required, at the top)

Use this text verbatim (or a close paraphrase that keeps every guardrail):

> **Reviewer-assist, not a reviewer.** The signals below are sort/triage hints for a human reviewer. The composite score is a queue-sort aid, not an accept/reject verdict. Compliance `FAIL` means "a human should look at this first." Verify every citation, claim, score, and rationale against the paper itself before acting on any of this.

### 2. At-a-glance table (required)

One row per config. Use the exact columns below.

```
| Config | Composite | Recommendation | Compliance | Claims verified | Hallucinations |
|--------|-----------|----------------|------------|-----------------|----------------|
| ieee   | **0.73**  | ACCEPT (hedge) | PASS       | 10 / 12         | 0              |
```

"Claims verified" pulls from `claims.verified_count` / `claims.total_claims`. "Hallucinations" is `claims.hallucination_count`.

### 3. Per-stage breakdown with bar indicators (required)

Render each of the four stages as a 10-segment bar (`█` filled, `░` empty, one block per 10% of [0,1]), followed by the raw subscore and a one-line rationale quoted from the record. Order: compliance → verification → depth → rubric.

```
compliance     ████████░░  0.80  PASS — all required sections present; anonymization checks pass.
verification   █████████░  0.90  10 / 12 claims verified via CrossRef; 2 fell back to heuristic.
depth          ████░░░░░░  0.42  Methodology thin on ablations; limitations section missing.
rubric         ████████░░  0.78  Strong novelty (4.5/5); weak reproducibility (2.0/5).
```

Sources for each rationale:
- `compliance` line → `compliance.triage` + joined `compliance.issues[]` (if empty, say "no issues flagged").
- `verification` line → `claims.verified_count` / `total_claims` + a note if any `VerificationResult.source == "heuristic"` or `"none"`.
- `depth` line → weakest of the four depth subscores + matching `depth.rationales[<key>]`.
- `rubric` line → highest and lowest `rubric.dimensions[]` by `score/max_score`, with their `rationale` trimmed to one clause each.

If a stage was skipped (`extra.composite_breakdown[<stage>]` is null), render the bar as `──────────` and say "_skipped_" in place of the score.

### 4. Rubric dimensions table (required when `rubric` is present)

One row per `rubric.dimensions[]` entry. Quote the rationale verbatim — do not paraphrase.

```
| Dimension        | Score     | Rationale (from record)                                         |
|------------------|-----------|-----------------------------------------------------------------|
| novelty          | 4.5 / 5   | Two-stage retrieval method; no overlap found with prior work.   |
| soundness        | 3.0 / 5   | Ablations present but small; no statistical tests reported.     |
| ...              | ...       | ...                                                              |
```

If a dimension has no rationale, render `_no rationale recorded_` — never fabricate one.

### 5. Unverified / hallucinated claims (required, even if zero)

Walk `claims.results[]`. For every result where `verified == false` OR `hallucination_flag == true`, emit a bullet:

```
- **[hallucination]** claim `c17` (STATISTICAL, CRITICAL, confidence 0.31, source: crossref):
  "The method achieves 94.2% accuracy on ImageNet-1k."
  — Notes: cited paper's abstract reports 89.1%; evidence span does not match.
```

Fields: claim id, `claim_type`, `severity`, `VerificationResult.confidence`, `VerificationResult.source`, truncated claim text (~120 chars), and `VerificationResult.notes` verbatim. Bold `**[hallucination]**` only when `hallucination_flag == true`; otherwise use `[unverified]`. If the list is empty, write "_No unverified or flagged claims._" — do not omit the section.

### 6. Recommendation with hedge (required)

State the recommendation with an explicit hedge on the same line:

> Recommendation: **ACCEPT** — reviewer-queue sort signal, not a verdict.

Never drop the hedge, even for STRONG_ACCEPT or STRONG_REJECT. Compliance `FAIL` gets an additional line: *"Compliance triage is FAIL — a human should look at this paper first; the score does not override that signal."*

### 7. Artifact paths (required)

```
- Review draft: /Users/.../evalit-reports/<date>-<slug>/review.md
- Interactive HTML (with reweight sliders): /Users/.../<config>.html
- Machine-readable record: /Users/.../<config>.json
```

### 8. Verify footer (required, at the bottom)

> **Verify every claim.** These outputs come from a mix of heuristics, public-metadata APIs (CrossRef / Semantic Scholar / OpenAlex), and LLM sampling. Compliance checks can miss venue-specific rules. Verification sources can be stale or rate-limited. Rubric rationales are LLM-generated and may misread the paper. Open `review.md` or the HTML report for the full draft, and cross-check every item against the submission itself before you act. This tool supports the review process; it does not replace it.

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

`Read` the record's `extra.composite_breakdown` plus the stage-specific rationales (`rubric.dimensions[].rationale`, `depth.rationales`, etc.). Render the same 10-segment bar breakdown used in the main output template, then walk through the weighted contribution of the weakest stage:

```
compliance     ████████░░  0.80 × 0.15 = 0.120
verification   █████████░  0.90 × 0.20 = 0.180
depth          ████░░░░░░  0.42 × 0.20 = 0.084   ← weakest contributor
rubric         ████████░░  0.78 × 0.45 = 0.351
                                      composite = 0.735
```

Then explain in one sentence tied to the rationale: *"Depth drags the composite because `depth.rationales['methodology']` flags missing ablations. Rubric is solid but under-weighted at 0.45. Drop the depth weight to 0.05 (rubric-heavy preset) and the composite rises to 0.77 (ACCEPT)."* Quote the rationale, don't invent one.

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

- **Do** include the reviewer-assist banner and verify footer in every paper-review response. They are not optional.
- **Do** `Read` `record.json` before presenting a review so you can quote per-stage rationales. Never describe a subscore without quoting the source rationale from the record.
- **Do** render per-stage subscores with the 10-segment bar indicator (`█░`), not just numbers.
- **Do** list the unverified/hallucinated-claims section every time, even when empty (write "_No unverified or flagged claims._"). Silent omission reads as zero and that is sometimes wrong.
- **Do** relay file paths so the user can open HTML reports (`/path/to/ieee.html`, etc.).
- **Do** mention that the HTML report has **in-browser reweight sliders** when the user wants to explore weights outside chat.
- **Do** frame compliance `FAIL` as "a human should look at this first," not auto-reject.
- **Don't** present a composite number without the per-stage breakdown + rationales. A standalone composite is an acceptance lure, not a review.
- **Don't** paraphrase or invent rationales. Quote `rubric.dimensions[].rationale`, `depth.rationales[<key>]`, `compliance.issues[]`, and `VerificationResult.notes` verbatim. If a rationale is absent, say so ("_no rationale recorded_") rather than making one up.
- **Don't** drop the recommendation hedge, even on STRONG_ACCEPT / STRONG_REJECT. It is always "a reviewer-queue sort signal, not a verdict."
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
