"""Static HTML report — self-contained single-file evaluation view.

Consumes an `EvaluationRecord`, produces an HTML string with inline CSS
and no external JS. Shareable via email, email-able, archivable.

Uses `markdown-it-py` to render each section builder's markdown into HTML;
`markdown-it-py` ships transitively with typer/rich so no new dep is needed.
"""

from __future__ import annotations

import html
from datetime import datetime

from markdown_it import MarkdownIt

from evalit_4me.contracts import EvaluationRecord
from evalit_4me.dashboard.app import build_view_sections
from evalit_4me.formatters.reviewer import format_review_draft

_md = MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True}).enable(
    "table"
)


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
"""


def render_report_html(record: EvaluationRecord) -> str:
    draft = format_review_draft(record)
    title = record.paper.metadata.title or "(untitled)"
    triage = record.compliance.triage.value
    subtitle = (
        f"{record.paper.id} · "
        f"recommendation: <strong>{draft.recommendation.value}</strong> · "
        f"score: <strong>{draft.overall_score:.2f}</strong> · "
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

    generated_at = datetime.now().isoformat(timespec="seconds")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>evalit-4me report — {html.escape(title)}</title>
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
{"".join(body_parts)}
<footer>
evalit-4me v{record.provenance.evalit_version} ·
config {record.provenance.config_hash} ·
generated {generated_at}
</footer>
</main>
</body>
</html>
"""
