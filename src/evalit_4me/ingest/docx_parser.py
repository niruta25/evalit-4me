"""`.docx` ingest via `mammoth` → markdown.

mammoth converts Word paragraph styles into markdown headings (Heading 1
→ `#`, Heading 2 → `##`, etc.) and preserves bold/italic, lists, and
tables. Its markdown output plugs directly into `parse_markdown` after a
light clean-up pass (mammoth prefixes every heading with an inline
`<a id="...">` anchor that blocks the ATX regex).

Math rendered in OMML does not round-trip cleanly — mammoth emits the raw
text or the image placeholder. For math-dense papers, prefer marker.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from evalit_4me.contracts import Paper
from evalit_4me.ingest.errors import IngestError, ParseError
from evalit_4me.ingest.parser import parse_markdown

# mammoth prepends a heading anchor tag on the same line as the header,
# e.g. `<a id="abstract"></a>## Abstract`. Strip it so our ATX regex can
# match. The anchors have no semantic value for evalit's downstream
# stages.
_ANCHOR_PREFIX_RE = re.compile(r'^\s*<a id="[^"]*"></a>\s*', re.MULTILINE)

# mammoth also escapes hyphens and parentheses with backslashes (markdown
# "safe" mode). Unescape them for readability and for regex hits on
# things like arXiv IDs in the body.
_ESCAPED_CHARS_RE = re.compile(r"\\([-\\().*_\[\]!])")


class MammothNotInstalledError(IngestError):
    """mammoth is not available. Install the `[docx]` extra."""


def parse_docx(docx_path: Path | str) -> Paper:
    """Parse a `.docx` file via mammoth and return a `Paper`."""
    try:
        import mammoth
    except ImportError as exc:
        raise MammothNotInstalledError(
            "mammoth is required for .docx parsing. Install with: pip install 'evalit-4me[docx]'"
        ) from exc

    path = Path(docx_path)
    if not path.exists():
        raise FileNotFoundError(f".docx not found: {path}")

    with path.open("rb") as fh:
        result = mammoth.convert_to_markdown(fh)

    markdown = _clean_mammoth_output(result.value or "")
    if not markdown.strip():
        raise ParseError(f"mammoth extracted no text from {path}")

    paper_id = _paper_id_from_docx(path)
    return parse_markdown(markdown, paper_id=paper_id, source_name=path.name)


def _clean_mammoth_output(markdown: str) -> str:
    cleaned = _ANCHOR_PREFIX_RE.sub("", markdown)
    cleaned = _ESCAPED_CHARS_RE.sub(r"\1", cleaned)
    return cleaned


def _paper_id_from_docx(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return f"docx:{digest}"
