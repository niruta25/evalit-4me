"""Metadata-match scoring: sub-scores and overall match_ok threshold."""

from __future__ import annotations

from evalit_4me.contracts import Reference
from evalit_4me.stages.verify.citation_exists import ExternalMetadata
from evalit_4me.stages.verify.citation_metadata import compare_metadata


def test_perfect_match():
    ref = Reference(
        id="r",
        raw="...",
        title="Attention Is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer"],
        year=2017,
        venue="NeurIPS",
    )
    found = ExternalMetadata(
        title="Attention Is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer"],
        year=2017,
        venue="NeurIPS",
    )
    m = compare_metadata(ref, found)
    assert m.overall > 0.95
    assert m.match_ok is True
    assert m.mismatches == ()


def test_year_off_by_one():
    ref = Reference(id="r", raw="...", title="X", authors=["Smith"], year=2020)
    found = ExternalMetadata(title="X", authors=["Smith"], year=2021, venue=None)
    m = compare_metadata(ref, found)
    assert 0.7 <= m.year_score <= 0.9  # ~0.8 by our rubric
    # Still OK overall because title + author carry most of the weight.
    assert m.match_ok is True


def test_different_paper_same_year():
    """Title has zero overlap -> flagged as mismatch even if year matches."""
    ref = Reference(id="r", raw="...", title="Deep learning", authors=["LeCun"], year=2015)
    found = ExternalMetadata(
        title="Variational inference for beginners",
        authors=["LeCun"],
        year=2015,
        venue=None,
    )
    m = compare_metadata(ref, found)
    assert "title" in m.mismatches
    assert m.match_ok is False


def test_author_surname_extraction_various_formats():
    """Authors can appear as 'Last, First', 'First Last', etc."""
    ref = Reference(id="r", raw="...", title="X", authors=["LeCun, Y.", "Bengio, Y."])
    found = ExternalMetadata(title="X", authors=["Yann LeCun", "Yoshua Bengio"])
    m = compare_metadata(ref, found)
    assert m.author_score >= 0.5


def test_missing_fields_on_both_sides_neutral():
    """Fields missing on both sides shouldn't penalize."""
    ref = Reference(id="r", raw="...", title=None, authors=[], year=None, venue=None)
    found = ExternalMetadata(title=None, authors=[], year=None, venue=None)
    m = compare_metadata(ref, found)
    # With everything neutral, overall stays high because no negative signal.
    assert m.overall >= 0.9


def test_venue_substring_counts():
    ref = Reference(id="r", raw="...", title="X", authors=["Y"], year=2020, venue="ICLR")
    found = ExternalMetadata(
        title="X",
        authors=["Y"],
        year=2020,
        venue="International Conference on Learning Representations (ICLR)",
    )
    m = compare_metadata(ref, found)
    assert m.venue_score >= 0.5


def test_match_ok_threshold():
    """A partially-matching record below threshold isn't ok."""
    ref = Reference(id="r", raw="...", title="A B C D", authors=["X"], year=2020)
    found = ExternalMetadata(title="E F G H", authors=["Y"], year=2021)
    m = compare_metadata(ref, found)
    assert m.match_ok is False
