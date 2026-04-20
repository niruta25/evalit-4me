"""Static HTML report — self-contained single-file evaluation view.

Consumes an `EvaluationRecord`, produces an HTML string with inline CSS
and inline JS. Shareable via email, archivable, no server.

Interactive reweighting: the report embeds the `composite_breakdown` +
default weights as JSON and exposes four range sliders. Editing a slider
recomputes the composite in-browser using the same formula as
`skill_helpers.recompute_composite` and updates the score + recommendation
live. A "copy review markdown" button copies the review draft to clipboard.
"""

from __future__ import annotations

import html
import json
from datetime import datetime

from markdown_it import MarkdownIt

from evalit_4me.contracts import EvaluationRecord
from evalit_4me.formatters.reviewer import format_review_draft, render_review_markdown
from evalit_4me.formatters.sections import build_view_sections

_md = MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True}).enable(
    "table"
)


# Keep the default-weight block in sync with `ScoringConfig.weights` —
# these four keys match the stage subscore keys in `composite_breakdown`.
_DEFAULT_WEIGHTS = {
    "compliance": 0.15,
    "verification": 0.20,
    "depth": 0.20,
    "rubric": 0.45,
}


_RECOMMENDATION_THRESHOLDS_JS = [
    (0.85, "STRONG_ACCEPT"),
    (0.70, "ACCEPT"),
    (0.55, "WEAK_ACCEPT"),
    (0.45, "BORDERLINE"),
    (0.30, "WEAK_REJECT"),
    (0.15, "REJECT"),
]


_CSS = """
:root {
  --bg: #ffffff;
  --fg: #1f2328;
  --muted: #656d76;
  --accent: #0969da;
  --border: #d0d7de;
  --chip-pass: #1a7f37;
  --chip-cond: #bf8700;
  --chip-fail: #cf222e;
  --code-bg: #f6f8fa;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  color: var(--fg);
  background: var(--bg);
  margin: 0;
  padding: 0;
  line-height: 1.55;
}
main {
  max-width: 960px;
  margin: 0 auto;
  padding: 32px 24px 80px;
}
header {
  border-bottom: 2px solid var(--border);
  padding-bottom: 16px;
  margin-bottom: 32px;
}
header h1 {
  margin: 0 0 6px;
  font-size: 1.6rem;
}
header .subtitle {
  color: var(--muted);
  font-size: 0.95rem;
}
.triage-chip {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: uppercase;
  color: #fff;
  margin-left: 8px;
  vertical-align: middle;
}
.triage-PASS { background: var(--chip-pass); }
.triage-CONDITIONAL { background: var(--chip-cond); }
.triage-FAIL { background: var(--chip-fail); }
section {
  margin: 32px 0;
  padding: 20px 24px;
  border: 1px solid var(--border);
  border-radius: 8px;
}
section > h2 {
  margin-top: 0;
  font-size: 1.2rem;
  border-bottom: 1px solid var(--border);
  padding-bottom: 8px;
}
section.score-card ul {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
section.score-card li { padding: 10px 0; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 10px 0;
}
th, td {
  border: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}
th { background: var(--code-bg); font-weight: 600; }
code, pre {
  background: var(--code-bg);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.9rem;
}
pre {
  padding: 12px 14px;
  border-radius: 6px;
  overflow-x: auto;
  white-space: pre-wrap;
}
code { padding: 1px 4px; border-radius: 3px; }
blockquote {
  border-left: 4px solid var(--accent);
  margin: 8px 0;
  padding: 2px 12px;
  color: var(--muted);
}
a { color: var(--accent); }
footer {
  margin-top: 40px;
  color: var(--muted);
  font-size: 0.85rem;
  border-top: 1px solid var(--border);
  padding-top: 16px;
}

/* Reweight panel */
section.reweight .sliders {
  display: grid;
  grid-template-columns: 140px 1fr 60px;
  gap: 8px 16px;
  align-items: center;
  margin: 12px 0 20px;
}
section.reweight .slider-label {
  font-weight: 500;
}
section.reweight input[type="range"] {
  width: 100%;
}
section.reweight .slider-value {
  text-align: right;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.9rem;
}
section.reweight .live-score {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  padding: 12px 14px;
  background: var(--code-bg);
  border-radius: 6px;
  margin-bottom: 12px;
}
section.reweight .live-score .label {
  color: var(--muted);
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}
section.reweight .live-score .value {
  font-size: 1.25rem;
  font-weight: 600;
}
section.reweight .controls {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}
section.reweight button {
  padding: 6px 14px;
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
}
section.reweight button:hover {
  background: var(--code-bg);
}
.copy-button {
  margin-top: 8px;
}
"""


def render_report_html(record: EvaluationRecord) -> str:
    draft = format_review_draft(record)
    title = record.paper.metadata.title or "(untitled)"
    triage = record.compliance.triage.value
    subtitle = (
        f"{record.paper.id} &middot; "
        f'recommendation: <strong id="hdr-recommendation">{draft.recommendation.value}</strong>'
        f" &middot; "
        f'score: <strong id="hdr-score">{draft.overall_score:.2f}</strong> &middot; '
        f"confidence: {draft.reviewer_confidence:.2f}"
    )

    sections = build_view_sections(record)
    body_parts: list[str] = []
    for sec in sections:
        css_class = "score-card" if sec.title == "Score card" else ""
        body_parts.append(
            f'<section class="{css_class}">\n'
            f"<h2>{html.escape(sec.title)}</h2>\n"
            f"{_md.render(sec.body_markdown)}\n"
            f"</section>"
        )

    reweight_section = _render_reweight_section(draft)
    review_md = render_review_markdown(draft)
    embed = _embed_record_blob(draft, review_md)

    generated_at = datetime.now().isoformat(timespec="seconds")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>evalit-4me report &mdash; {html.escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<header>
<h1>{html.escape(title)}
<span class="triage-chip triage-{triage}">{triage}</span>
</h1>
<div class="subtitle">{subtitle}</div>
</header>
{reweight_section}
{"".join(body_parts)}
<footer>
evalit-4me v{record.provenance.evalit_version} &middot;
config {record.provenance.config_hash} &middot;
generated {generated_at}
</footer>
</main>
{embed}
<script>{_REWEIGHT_JS}</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Reweight panel (Task 2a)
# ---------------------------------------------------------------------------


def _render_reweight_section(draft) -> str:
    """Static markup for the interactive reweight panel.

    The JS handler reads `composite_breakdown` from the embedded JSON blob
    and recomputes on every slider `input` event.
    """
    slider_rows: list[str] = []
    for key, default in _DEFAULT_WEIGHTS.items():
        slider_rows.append(
            f'<label class="slider-label" for="weight-{key}">{key}</label>'
            f'<input type="range" id="weight-{key}" name="{key}" '
            f'min="0" max="1" step="0.01" value="{default}" data-default="{default}">'
            f'<span class="slider-value" id="weight-{key}-value">{default:.2f}</span>'
        )
    return f"""
<section class="reweight">
<h2>Interactive reweight</h2>
<p>Drag the sliders to try different weight sets. The composite score and recommendation
update live &mdash; no pipeline re-run.</p>
<div class="live-score">
<div><div class="label">Composite</div>
<div class="value" id="live-composite">{draft.overall_score:.3f}</div></div>
<div><div class="label">Recommendation</div>
<div class="value" id="live-recommendation">{draft.recommendation.value}</div></div>
<div><div class="label">Δ vs defaults</div>
<div class="value" id="live-delta">0.000</div></div>
</div>
<div class="sliders">
{"".join(slider_rows)}
</div>
<div class="controls">
<button type="button" id="reset-weights">Reset to defaults</button>
<button type="button" id="copy-review-md">Copy review markdown</button>
</div>
</section>
"""


def _embed_record_blob(draft, review_md: str) -> str:
    """Emit the embedded JSON the JS handler reads from.

    Kept separate from `<script>` logic so it's trivially findable in the
    rendered HTML (tests grep for it; reviewers can inspect it).
    """
    breakdown = {k: v for k, v in draft.composite_breakdown.items()}
    blob = {
        "breakdown": breakdown,
        "defaults": _DEFAULT_WEIGHTS,
        "thresholds": _RECOMMENDATION_THRESHOLDS_JS,
        "original_composite": draft.overall_score,
        "review_markdown": review_md,
    }
    payload = json.dumps(blob)
    return f'<script type="application/json" id="evalit-record">{payload}</script>'


# Inline JS handler. Mirrors `skill_helpers.recompute_composite`:
#   composite = Σ (subscore[k] * weight[k]) / Σ weight[k]     # present stages only
# Stages absent from breakdown (e.g. verification when no claims) are skipped
# and their weight excluded from the denominator, matching the server-side
# redistribution rule.
_REWEIGHT_JS = """
(function () {
  var blobEl = document.getElementById('evalit-record');
  if (!blobEl) return;
  var blob;
  try { blob = JSON.parse(blobEl.textContent); } catch (e) { return; }

  var keys = Object.keys(blob.defaults);

  function readWeights() {
    var w = {};
    keys.forEach(function (k) {
      var el = document.getElementById('weight-' + k);
      w[k] = el ? parseFloat(el.value) : blob.defaults[k];
    });
    return w;
  }

  function recompute(weights) {
    var numerator = 0;
    var denominator = 0;
    keys.forEach(function (k) {
      var sub = blob.breakdown[k];
      if (sub === null || sub === undefined) return;
      numerator += sub * weights[k];
      denominator += weights[k];
    });
    return denominator > 0 ? numerator / denominator : 0;
  }

  function classify(composite) {
    for (var i = 0; i < blob.thresholds.length; i++) {
      var t = blob.thresholds[i];
      if (composite >= t[0]) return t[1];
    }
    return 'STRONG_REJECT';
  }

  function update() {
    var weights = readWeights();
    keys.forEach(function (k) {
      var v = document.getElementById('weight-' + k + '-value');
      if (v) v.textContent = weights[k].toFixed(2);
    });
    var composite = recompute(weights);
    var rec = classify(composite);
    var delta = composite - blob.original_composite;
    setText('live-composite', composite.toFixed(3));
    setText('live-recommendation', rec);
    setText('live-delta', (delta >= 0 ? '+' : '') + delta.toFixed(3));
    setText('hdr-score', composite.toFixed(2));
    setText('hdr-recommendation', rec);
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  keys.forEach(function (k) {
    var el = document.getElementById('weight-' + k);
    if (el) el.addEventListener('input', update);
  });

  var reset = document.getElementById('reset-weights');
  if (reset) {
    reset.addEventListener('click', function () {
      keys.forEach(function (k) {
        var el = document.getElementById('weight-' + k);
        if (el) el.value = blob.defaults[k];
      });
      update();
    });
  }

  var copy = document.getElementById('copy-review-md');
  if (copy) {
    copy.addEventListener('click', function () {
      var text = blob.review_markdown || '';
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          copy.textContent = 'Copied!';
          setTimeout(function () { copy.textContent = 'Copy review markdown'; }, 1500);
        });
      }
    });
  }
})();
"""
