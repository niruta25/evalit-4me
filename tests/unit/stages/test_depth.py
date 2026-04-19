"""Depth analyzer tests — per-dimension heuristics + fixture smoke."""

from __future__ import annotations

from pathlib import Path

import pytest

from evalit_4me.contracts import Paper, PaperMetadata, Section
from evalit_4me.ingest.parser import parse_markdown
from evalit_4me.stages.depth import analyze_depth

FIXTURES_DIR = Path(__file__).parents[2] / "fixtures" / "markdown"


def _paper(section_texts: dict[str, str]) -> Paper:
    """Build a Paper from a {title: text} dict. Order is dict order."""
    sections = [
        Section(id=t.lower().replace(" ", "-"), title=t, text=x, order=i)
        for i, (t, x) in enumerate(section_texts.items())
    ]
    return Paper(
        id="p",
        metadata=PaperMetadata(title="Test"),
        sections=sections,
    )


def test_methodology_full_signal():
    method_text = " ".join(
        [
            "We trained on the ImageNet dataset using Adam optimizer.",
            "Compared to baselines, our model achieves higher accuracy.",
            "An ablation study removes components one at a time.",
            "We report F1 and precision as the main metrics.",
            "This section runs long with many additional words to ensure the",
            "length gate trips. " * 40,
        ]
    )
    paper = _paper(
        {
            "Introduction": "intro",
            "Method": method_text,
            "Results": "results",
            "Conclusion": "conclusion",
        }
    )
    report = analyze_depth(paper)
    assert report.methodology_score == 1.0
    assert "dataset_mentioned" in report.rationales["methodology"]


def test_methodology_partial_signal():
    paper = _paper(
        {
            "Introduction": "i",
            "Method": "We describe our approach.",
            "Results": "r",
            "Conclusion": "c",
        }
    )
    report = analyze_depth(paper)
    assert 0.0 <= report.methodology_score < 0.5


def test_methodology_absent_scores_zero():
    paper = _paper({"Introduction": "i", "Results": "r", "Conclusion": "c"})
    report = analyze_depth(paper)
    assert report.methodology_score == 0.0


def test_limitations_dedicated_section():
    long_limitations = (
        "Our work has several limitations we wish to discuss. "
        "First, the dataset is English-only. Second, compute constraints "
        "limited hyperparameter search. Third, we did not evaluate on "
        "low-resource languages. "
    ) * 3  # ~60 * 3 = 180+ words
    paper = _paper(
        {
            "Introduction": "i",
            "Method": "m",
            "Results": "r",
            "Limitations": long_limitations,
            "Conclusion": "c",
        }
    )
    report = analyze_depth(paper)
    # ~180/200 = 0.9, but capped at a floor of 0.5 for *presence* of section.
    assert report.limitations_score >= 0.5


def test_limitations_absent_but_mentioned_in_conclusion():
    paper = _paper(
        {
            "Introduction": "i",
            "Method": "m",
            "Results": "r",
            "Conclusion": "We note a limitation: our work cannot handle non-English inputs.",
        }
    )
    report = analyze_depth(paper)
    assert 0.0 < report.limitations_score < 0.5


def test_limitations_completely_absent():
    paper = _paper({"Introduction": "i", "Method": "m", "Results": "r", "Conclusion": "c"})
    report = analyze_depth(paper)
    assert report.limitations_score == 0.0


def test_reproducibility_all_signals():
    text = (
        "Code available at https://github.com/foo/bar. "
        "We set torch.manual_seed(42) for reproducibility. "
        "We use the Adam optimizer with learning rate 0.001 and batch size 64. "
        "Experiments run on the CIFAR-10 dataset."
    )
    paper = _paper({"Introduction": text, "Method": "m", "Results": "r", "Conclusion": "c"})
    report = analyze_depth(paper)
    assert report.reproducibility_score == 1.0


def test_reproducibility_partial():
    text = "We use the ImageNet dataset."
    paper = _paper({"Introduction": text, "Method": "m", "Results": "r", "Conclusion": "c"})
    report = analyze_depth(paper)
    # Only dataset_named hit -> 1/4 = 0.25.
    assert report.reproducibility_score == 0.25


def test_reproducibility_none():
    paper = _paper(
        {
            "Introduction": "vague prose",
            "Method": "vague method",
            "Results": "numbers",
            "Conclusion": "done",
        }
    )
    report = analyze_depth(paper)
    assert report.reproducibility_score == 0.0


def test_logical_soundness_full_skeleton():
    paper = _paper(
        {
            "Introduction": "We motivate our transformer model and its advantages.",
            "Method": "We describe the transformer model architecture in detail.",
            "Results": "Our transformer model shows improved accuracy on benchmarks.",
            "Conclusion": "Our transformer model demonstrates better benchmark accuracy.",
        }
    )
    report = analyze_depth(paper)
    assert report.logical_soundness_score >= 1.0 - 1e-6  # exactly 1.0 with bonus


def test_logical_soundness_missing_conclusion():
    paper = _paper({"Introduction": "i", "Method": "m", "Results": "r"})
    report = analyze_depth(paper)
    assert report.logical_soundness_score == 0.75


def test_all_scores_in_unit_interval():
    """Pydantic contract: every dimension must be in [0, 1]."""
    paper = _paper({"Introduction": "i", "Method": "m", "Results": "r", "Conclusion": "c"})
    r = analyze_depth(paper)
    for value in (
        r.methodology_score,
        r.limitations_score,
        r.reproducibility_score,
        r.logical_soundness_score,
    ):
        assert 0.0 <= value <= 1.0


def test_rationales_present_for_all_dimensions():
    paper = _paper({"Introduction": "i", "Method": "m", "Results": "r", "Conclusion": "c"})
    r = analyze_depth(paper)
    assert set(r.rationales.keys()) == {
        "methodology",
        "limitations",
        "reproducibility",
        "logical_soundness",
    }
    assert all(isinstance(v, str) and v for v in r.rationales.values())


@pytest.mark.parametrize(
    "fixture_name",
    [
        "paper_01_numbered_refs",
        "paper_02_doi_heavy",
        "paper_03_bulleted_refs",
        "paper_04_no_refs_section",
        "paper_05_mixed_refs",
    ],
)
def test_fixture_papers_produce_valid_depth_report(fixture_name: str):
    md = (FIXTURES_DIR / f"{fixture_name}.md").read_text(encoding="utf-8")
    paper = parse_markdown(md, source_name=fixture_name)
    report = analyze_depth(paper)
    # Every dimension in range.
    for v in (
        report.methodology_score,
        report.limitations_score,
        report.reproducibility_score,
        report.logical_soundness_score,
    ):
        assert 0.0 <= v <= 1.0


def test_known_reproducible_paper_flags_reproducibility():
    """Exit gate: reproducibility flag correct on known-reproducible paper.
    paper_03 mentions arXiv, figures, and typical DL language; we assert the
    signal is at least non-zero, since it has dataset + hyperparameter cues."""
    md = (FIXTURES_DIR / "paper_03_bulleted_refs.md").read_text(encoding="utf-8")
    paper = parse_markdown(md, source_name="paper_03_bulleted_refs")
    report = analyze_depth(paper)
    assert report.reproducibility_score > 0.0
