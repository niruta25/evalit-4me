"""Reference-extractor unit tests (pure-function, no fixtures)."""

from __future__ import annotations

from evalit_4me.ingest.reference_extractor import extract_references


def test_empty_input_returns_empty_list():
    assert extract_references("") == []
    assert extract_references("   \n\n  ") == []


def test_numbered_reference_with_arxiv():
    text = "[1] Kingma, D. P., and Ba, J. (2015). Adam: A method for stochastic optimization. arXiv:1412.6980."
    refs = extract_references(text)
    assert len(refs) == 1
    r = refs[0]
    assert r.year == 2015
    assert r.arxiv_id == "1412.6980"
    assert r.title is not None and "Adam" in r.title


def test_bulleted_reference_with_doi():
    text = (
        "- LeCun, Y., Bengio, Y., and Hinton, G. (2015). "
        "Deep learning. Nature, 521(7553), 436-444. doi:10.1038/nature14539"
    )
    refs = extract_references(text)
    assert len(refs) == 1
    assert refs[0].doi == "10.1038/nature14539"
    assert refs[0].year == 2015
    assert "Deep learning" in (refs[0].title or "")


def test_multiple_numbered_entries_split_correctly():
    text = (
        "[1] Smith, J. (2020). First paper. Venue A.\n"
        "[2] Doe, J. (2021). Second paper. Venue B.\n"
        "[3] Roe, J. (2022). Third paper. Venue C."
    )
    refs = extract_references(text)
    assert len(refs) == 3
    assert [r.year for r in refs] == [2020, 2021, 2022]


def test_blank_line_separated_paragraphs():
    text = (
        "Gilmer, J. et al. (2017). Neural message passing for quantum chemistry. arXiv:1704.01212.\n"
        "\n"
        "Kipf, T. (2017). Semi-supervised classification with GCNs. arXiv:1609.02907."
    )
    refs = extract_references(text)
    assert len(refs) == 2
    assert refs[0].arxiv_id == "1704.01212"
    assert refs[1].arxiv_id == "1609.02907"


def test_continuation_lines_folded_into_entry():
    text = (
        "[1] Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L.,\n"
        "    Gomez, A. N., Kaiser, L., and Polosukhin, I. (2017). Attention is\n"
        "    all you need. NeurIPS."
    )
    refs = extract_references(text)
    assert len(refs) == 1
    assert refs[0].year == 2017
    assert "Attention is all you need" in (refs[0].title or "")


def test_doi_recognized_without_prefix():
    text = "[1] Author (2020). A paper. Journal, 10.1234/abcd.5678."
    refs = extract_references(text)
    assert len(refs) == 1
    assert refs[0].doi == "10.1234/abcd.5678"


def test_arxiv_with_version_suffix():
    text = "[1] Author (2021). Title. arXiv:2103.00001v2."
    refs = extract_references(text)
    assert refs[0].arxiv_id == "2103.00001"


def test_no_year_still_produces_entry():
    text = "[1] Author. Title without a year. Journal."
    refs = extract_references(text)
    assert len(refs) == 1
    assert refs[0].year is None
    assert refs[0].title is not None
