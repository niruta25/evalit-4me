"""Markdown (marker_single output) -> `Paper` contract.

Section detection is regex-based on ATX headers (`#`, `##`, ...). We don't
use a full markdown AST because the only structural features we care about
are headers, image links (figures), and pipe tables.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from evalit_4me.contracts import Figure, Paper, PaperMetadata, Section, Table
from evalit_4me.ingest.errors import ParseError
from evalit_4me.ingest.marker_runner import DEFAULT_BINARY, DEFAULT_TIMEOUT_SEC, MarkerRunner
from evalit_4me.ingest.reference_extractor import extract_references

HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")

# Section numbering prefix, e.g. "1. ", "2.1 ", "3 ", "A.1 ", "I. ", "VII. ".
# Applied to section titles so downstream compliance / rubric stages can
# match on clean canonical names like "Introduction" instead of
# "1. Introduction" or "VII. REFERENCES" (IEEE style).
SECTION_NUMBER_PREFIX_RE = re.compile(
    r"^(?:"
    r"[A-Z]\.?\s*\d+(?:\.\d+)*\.?\s+"  # "A.1 " / "B.2.1 "
    r"|\d+(?:\.\d+)*\.?\s+"  # "1. " / "2.1 "
    r"|[IVXLCDM]{1,5}\.?\s+"  # Roman numerals "I. " / "VII. "
    r")",
    re.IGNORECASE,
)

REFERENCE_HEADERS = {
    "references",
    "bibliography",
    "works cited",
    "citations",
}

# Headers that look like prose and should NOT start a section (marker
# sometimes emits "Abstract" as a header, which is fine — we treat it as
# a section, not as metadata).


def parse_pdf(
    pdf_path: Path | str,
    *,
    binary: str = DEFAULT_BINARY,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> Paper:
    """Run marker on a PDF and parse its output into a `Paper`."""
    pdf = Path(pdf_path)
    runner = MarkerRunner(binary=binary, timeout_sec=timeout_sec)
    markdown = runner.run(pdf)
    paper_id = _paper_id_from_pdf(pdf)
    return parse_markdown(markdown, paper_id=paper_id, source_name=pdf.name)


def parse_markdown(
    markdown: str,
    *,
    paper_id: str | None = None,
    source_name: str | None = None,
) -> Paper:
    """Parse marker-style markdown into a `Paper`.

    `source_name` is purely informational; `paper_id` is hashed from the
    markdown bytes if not supplied so identity is content-stable.
    """
    if not markdown.strip():
        raise ParseError("Empty markdown input.")

    pid = paper_id or _paper_id_from_text(markdown)
    blocks = _split_into_header_blocks(markdown)
    if not blocks:
        raise ParseError("No content blocks detected in markdown.")

    title = _extract_title(blocks)
    sections, references_body = _build_sections(blocks)

    if not sections:
        # Single-section fallback: treat the whole body as one section.
        sections = [Section(id="body", title="Body", text=markdown.strip(), order=0)]

    # Drop empty sections so the exit-gate invariant "every section non-empty" holds.
    sections = [s for s in sections if s.text.strip()]

    references = extract_references(references_body) if references_body else []
    figures = _extract_figures(markdown)
    tables = _extract_tables(markdown)
    abstract = _extract_abstract(sections)

    return Paper(
        id=pid,
        metadata=PaperMetadata(
            title=title or (source_name or "Untitled"),
            authors=[],
            abstract=abstract,
        ),
        sections=sections,
        references=references,
        figures=figures,
        tables=tables,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _paper_id_from_pdf(pdf: Path) -> str:
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()[:16]
    return f"pdf:{digest}"


def _paper_id_from_text(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"md:{digest}"


def _split_into_header_blocks(markdown: str) -> list[tuple[int, str, str]]:
    """Return (level, header_title, body_text) tuples in document order.

    Content before the first header is attached as a leading block with
    level=0 and title="". Empty-body blocks are allowed here — the caller
    drops them later.
    """
    lines = markdown.splitlines()
    blocks: list[tuple[int, str, list[str]]] = [(0, "", [])]
    for ln in lines:
        m = HEADER_RE.match(ln)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            blocks.append((level, title, []))
        else:
            blocks[-1][2].append(ln)
    return [(lvl, title, "\n".join(body).strip()) for lvl, title, body in blocks]


def _extract_title(blocks: list[tuple[int, str, str]]) -> str | None:
    """First H1 is the paper title (marker convention)."""
    for level, title, _body in blocks:
        if level == 1 and title:
            return title
    return None


def _build_sections(
    blocks: list[tuple[int, str, str]],
) -> tuple[list[Section], str]:
    """Convert blocks into `Section`s and return the references body separately.

    References are pulled out so the section list doesn't contain free-form
    citation text that'd confuse the depth / claims stages.
    """
    sections: list[Section] = []
    references_body = ""
    order = 0

    for idx, (level, title, body) in enumerate(blocks):
        # Skip the title H1 entirely — it's metadata, not a section.
        if level == 1 and idx == 0:
            continue
        if level == 1 and idx > 0 and not sections:
            # If the first thing is H1 but prefixed by a leading block, skip it too.
            continue

        if not title and not body:
            continue

        section_title = _normalize_title(title) or "Introduction"
        # Check references header on *both* raw and normalized forms so
        # IEEE-style "VII. REFERENCES" and plain "References" both match.
        if (
            title.strip().lower() in REFERENCE_HEADERS
            or section_title.strip().lower() in REFERENCE_HEADERS
        ):
            references_body = body
            continue
        sections.append(
            Section(
                id=_slugify(section_title) or f"section-{order}",
                title=section_title,
                text=body,
                order=order,
            )
        )
        order += 1

    return sections, references_body


def _normalize_title(title: str) -> str:
    """Strip leading section numbering like "1.", "2.1", "A.1"."""
    stripped = SECTION_NUMBER_PREFIX_RE.sub("", title.strip(), count=1)
    return stripped.strip()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:64]


def _extract_figures(markdown: str) -> list[Figure]:
    out: list[Figure] = []
    for idx, match in enumerate(IMAGE_RE.finditer(markdown), start=1):
        caption = match.group(1).strip() or None
        out.append(Figure(id=f"fig-{idx}", caption=caption, page=None))
    return out


def _extract_tables(markdown: str) -> list[Table]:
    """Count markdown pipe tables and grab an adjacent caption if present."""
    lines = markdown.splitlines()
    out: list[Table] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if (
            TABLE_ROW_RE.match(line)
            and i + 1 < len(lines)
            and TABLE_SEPARATOR_RE.match(lines[i + 1])
        ):
            caption = _nearby_table_caption(lines, i)
            out.append(Table(id=f"table-{len(out) + 1}", caption=caption, page=None))
            # Skip past this table's rows.
            j = i + 2
            while j < len(lines) and TABLE_ROW_RE.match(lines[j]):
                j += 1
            i = j
            continue
        i += 1
    return out


def _nearby_table_caption(lines: list[str], header_idx: int) -> str | None:
    """Return the nearest caption above/below a table, if any.

    Looks at the line immediately before the header (skipping blanks) for
    a "Table N:" or "Table N." prefix; otherwise looks one line after the
    last table row.
    """
    j = header_idx - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j >= 0 and re.match(r"^\s*\*?\*?Table\s+\d+[:.]", lines[j], re.IGNORECASE):
        return lines[j].strip().strip("*")
    return None


def _extract_abstract(sections: list[Section]) -> str | None:
    for section in sections:
        if section.title.strip().lower() == "abstract":
            return section.text.strip() or None
    return None
