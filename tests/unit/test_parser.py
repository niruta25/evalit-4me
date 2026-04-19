"""Parser tests + Chunk 1.3 exit-gate checks on the 5 markdown fixtures.

Exit gates enforced here:
  * ≥90% reference-extraction recall on the fixtures
  * every section non-empty
  * figure/table counts match manual counts
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalit_4me.contracts import Paper, Reference
from evalit_4me.ingest.errors import ParseError
from evalit_4me.ingest.parser import parse_markdown

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "markdown"
EXPECTED_PATH = Path(__file__).parents[1] / "fixtures" / "expected" / "fixtures.json"


def _load_expected() -> dict[str, dict]:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / f"{name}.md").read_text(encoding="utf-8")


def _matches_key(ref: Reference, key: dict) -> bool:
    if "arxiv_id" in key and ref.arxiv_id != key["arxiv_id"]:
        return False
    if "doi" in key and (ref.doi or "").lower() != str(key["doi"]).lower():
        return False
    if "title_contains" in key and (
        not ref.title or key["title_contains"].lower() not in ref.title.lower()
    ):
        return False
    return not ("year" in key and ref.year != key["year"])


# ---------------------------------------------------------------------------
# Generic parser behavior
# ---------------------------------------------------------------------------


def test_empty_markdown_raises():
    with pytest.raises(ParseError):
        parse_markdown("")


def test_single_section_fallback():
    paper = parse_markdown("Just a body with no headers at all.")
    assert len(paper.sections) == 1
    assert paper.sections[0].text.strip() == "Just a body with no headers at all."


def test_paper_id_is_content_stable():
    md = "# Title\n\n## Intro\n\nbody"
    a = parse_markdown(md)
    b = parse_markdown(md)
    assert a.id == b.id
    c = parse_markdown(md + "\n\nextra")
    assert a.id != c.id


def test_section_title_numbering_normalized():
    md = (
        "# Paper\n\n"
        "## 1. Introduction\n\nIntro body.\n\n"
        "## 2.1 Background\n\nBackground body.\n\n"
        "## A.1 Appendix Stuff\n\nAppendix body."
    )
    paper = parse_markdown(md)
    titles = [s.title for s in paper.sections]
    assert titles == ["Introduction", "Background", "Appendix Stuff"]


# ---------------------------------------------------------------------------
# Fixture-driven exit-gate checks
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def expected() -> dict[str, dict]:
    return _load_expected()


@pytest.fixture(scope="module", params=sorted(_load_expected().keys()))
def parsed_fixture(request) -> tuple[str, Paper]:
    name = request.param
    md = _load_fixture(name)
    return name, parse_markdown(md, source_name=name)


def test_title_extracted(parsed_fixture, expected):
    name, paper = parsed_fixture
    assert paper.metadata.title == expected[name]["title"]


def test_section_titles_match(parsed_fixture, expected):
    name, paper = parsed_fixture
    actual = [s.title for s in paper.sections]
    assert actual == expected[name]["section_titles"]


def test_every_section_non_empty(parsed_fixture):
    """Exit gate: every section non-empty."""
    _name, paper = parsed_fixture
    for section in paper.sections:
        assert section.text.strip(), f"Empty section: {section.title}"


def test_abstract_captured(parsed_fixture, expected):
    name, paper = parsed_fixture
    needle = expected[name]["abstract_contains"]
    assert paper.metadata.abstract is not None
    assert needle.lower() in paper.metadata.abstract.lower()


def test_figure_count_matches(parsed_fixture, expected):
    name, paper = parsed_fixture
    assert len(paper.figures) == expected[name]["figure_count"]


def test_table_count_matches(parsed_fixture, expected):
    name, paper = parsed_fixture
    assert len(paper.tables) == expected[name]["table_count"]


def test_reference_count_matches(parsed_fixture, expected):
    name, paper = parsed_fixture
    assert len(paper.references) == expected[name]["reference_count"]


def test_reference_recall_at_least_90_percent(expected):
    """Aggregate recall across all 5 fixtures must be ≥ 90%."""
    total_keys = 0
    matched_keys = 0
    per_paper: dict[str, float] = {}

    for name, spec in expected.items():
        paper = parse_markdown(_load_fixture(name), source_name=name)
        keys = spec["reference_keys"]
        if not keys:
            per_paper[name] = 1.0
            continue
        hits = 0
        for key in keys:
            if any(_matches_key(r, key) for r in paper.references):
                hits += 1
        total_keys += len(keys)
        matched_keys += hits
        per_paper[name] = hits / len(keys)

    overall = matched_keys / total_keys if total_keys else 1.0
    assert overall >= 0.90, f"Reference recall {overall:.2%} < 90%. Per-paper: {per_paper}"
