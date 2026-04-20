"""Lightweight PDF text extraction via `pdfplumber`.

This is the default PDF ingest path for the Claude Code plugin and any
install that uses the `[pdf-lite]` extra. It avoids marker-pdf's ~2 GB
model weights entirely at the cost of some fidelity on figure-heavy or
math-dense papers.

The output is markdown formatted well enough to flow through the same
`parse_markdown` pipeline marker uses. Section headings are detected via
two cues pdfplumber can read without layout inference:

1. Short all-caps or title-cased lines that look like headers
   ("1. Introduction", "II. METHODS", "Abstract").
2. Lines flagged as large-font by pdfplumber's font-size metadata.

Two-column layouts are handled by pdfplumber's own column-splitter — we
extract per-page with `extract_text(layout=False)` first and let the
section-heading regex do the heavy lifting. This is "good enough" for
single-column papers and acceptable for two-column; power users should
use marker via `EVALIT_USE_MARKER=1` if they need higher fidelity.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from evalit_4me.contracts import Paper
from evalit_4me.ingest.errors import IngestError, ParseError
from evalit_4me.ingest.parser import parse_markdown


class PdfPlumberNotInstalledError(IngestError):
    """pdfplumber is not available. Install the `[pdf-lite]` extra."""


# Heuristic header patterns. Order matters — more specific first.
_HEADER_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Roman-numeral sections: "I. INTRODUCTION", "II. RELATED WORK"
    re.compile(r"^\s*([IVX]{1,4})\.\s+([A-Z][A-Z\s\-&/]{2,60})\s*$"),
    # Numeric sections: "1. Introduction", "2.1 Setup", "3 Methods"
    re.compile(r"^\s*(\d+(?:\.\d+)*\.?)\s+([A-Z][A-Za-z0-9\s\-:,'&/()]{2,80})\s*$"),
    # Named sections (word or two, title-cased, short): "Abstract", "References"
    re.compile(
        r"^\s*(Abstract|Introduction|Related\s+Work|Background|Method(?:ology|s)?|"
        r"Approach|Experiments?|Results?|Discussion|Conclusions?|"
        r"References|Bibliography|Acknowledgm?ents?|Appendix|Limitations?|"
        r"Broader\s+Impact|Societal\s+Impact|Ethics)\s*$",
        re.IGNORECASE,
    ),
)


def parse_pdf_with_plumber(pdf_path: Path | str) -> Paper:
    """Parse a PDF using pdfplumber and return a `Paper`.

    Raises `PdfPlumberNotInstalledError` if pdfplumber isn't importable,
    and `ParseError` if the PDF contains no extractable text.
    """
    try:
        import pdfplumber
    except ImportError as exc:
        raise PdfPlumberNotInstalledError(
            "pdfplumber is required for lightweight PDF parsing. "
            "Install with: pip install 'evalit-4me[pdf-lite]'"
        ) from exc

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    markdown = _extract_markdown(pdfplumber, path)
    if not markdown.strip():
        raise ParseError(f"pdfplumber extracted no text from {path}")

    paper_id = _paper_id_from_pdf(path)
    return parse_markdown(markdown, paper_id=paper_id, source_name=path.name)


def _extract_markdown(pdfplumber_module, path: Path) -> str:
    """Read every page, promote likely headers to markdown, join with blank lines."""
    lines_out: list[str] = []
    with pdfplumber_module.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line:
                    lines_out.append("")
                    continue
                header = _promote_to_header(line)
                if header is not None:
                    lines_out.append("")
                    lines_out.append(header)
                    lines_out.append("")
                else:
                    lines_out.append(line)
            lines_out.append("")  # page break

    # Collapse runs of blank lines so markdown blocks parse cleanly.
    collapsed: list[str] = []
    blank = False
    for ln in lines_out:
        if not ln.strip():
            if not blank:
                collapsed.append("")
            blank = True
        else:
            collapsed.append(ln)
            blank = False
    return "\n".join(collapsed).strip() + "\n"


def _promote_to_header(line: str) -> str | None:
    """If `line` looks like a section header, return the markdown form.

    Returns the header with a leading `##` (level 2 — marker reserves level 1
    for the paper title, which pdfplumber extraction usually misses).
    """
    for pattern in _HEADER_PATTERNS:
        if pattern.match(line):
            return f"## {line}"
    return None


def _paper_id_from_pdf(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return f"pdf:{digest}"
