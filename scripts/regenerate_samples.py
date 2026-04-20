"""Generate sample_arxiv.pdf, sample_ieee.pdf PDFs from markdown samples.

Single-column and two-column layouts to exercise pdfplumber. Run with:

    uv run --with reportlab python /tmp/gen_samples.py
"""

from pathlib import Path

from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
)

EXAMPLES = Path("/Users/niruta.talwekar/Documents/GitHub/evalit-4me/plugin/examples")


def md_to_flowables(md: str, styles):
    flow = []
    title_style = ParagraphStyle(
        "title", parent=styles["Title"], fontSize=14, spaceAfter=14, alignment=1
    )
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11, spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle(
        "body",
        parent=styles["BodyText"],
        fontSize=10,
        leading=13,
        spaceAfter=6,
        alignment=TA_JUSTIFY,
    )

    for raw in md.split("\n\n"):
        block = raw.strip()
        if not block:
            continue
        if block.startswith("# "):
            flow.append(Paragraph(block[2:].replace("\n", " "), title_style))
            flow.append(Spacer(1, 0.08 * inch))
        elif block.startswith("## "):
            flow.append(Paragraph(block[3:].replace("\n", " "), h2))
        else:
            safe = block.replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")
            flow.append(Paragraph(safe, body))
    return flow


def single_column(src_md: Path, out_pdf: Path):
    md = src_md.read_text(encoding="utf-8")
    styles = getSampleStyleSheet()
    doc = BaseDocTemplate(
        str(out_pdf),
        pagesize=letter,
        leftMargin=0.8 * inch,
        rightMargin=0.8 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="col")
    doc.addPageTemplates([PageTemplate(id="single", frames=[frame])])
    doc.build(md_to_flowables(md, styles))


def two_column(src_md: Path, out_pdf: Path):
    md = src_md.read_text(encoding="utf-8")
    styles = getSampleStyleSheet()
    doc = BaseDocTemplate(
        str(out_pdf),
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )
    gap = 0.25 * inch
    col_w = (doc.width - gap) / 2
    left = Frame(
        doc.leftMargin, doc.bottomMargin, col_w, doc.height, id="L", leftPadding=0, rightPadding=0
    )
    right = Frame(
        doc.leftMargin + col_w + gap,
        doc.bottomMargin,
        col_w,
        doc.height,
        id="R",
        leftPadding=0,
        rightPadding=0,
    )
    doc.addPageTemplates([PageTemplate(id="two", frames=[left, right])])
    doc.build(md_to_flowables(md, styles))


if __name__ == "__main__":
    single_column(EXAMPLES / "sample_arxiv.md", EXAMPLES / "sample.pdf")
    two_column(EXAMPLES / "sample_ieee.md", EXAMPLES / "sample_twocol.pdf")
    print("wrote:", EXAMPLES / "sample.pdf", EXAMPLES / "sample_twocol.pdf")
