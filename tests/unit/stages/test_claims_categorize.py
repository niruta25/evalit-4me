"""Categorization rules: priority CITATION > STATISTICAL > TEMPORAL > CAPABILITY > EMPIRICAL."""

from __future__ import annotations

import pytest

from evalit_4me.contracts import ClaimType
from evalit_4me.stages.claims.categorize import categorize


@pytest.mark.parametrize(
    ("text", "has_refs", "expected"),
    [
        ("The method improves accuracy by 12.4%.", False, ClaimType.STATISTICAL),
        ("Our model achieves F1=0.91 on the benchmark.", False, ClaimType.STATISTICAL),
        ("We use the Transformer [3] as the backbone.", False, ClaimType.CITATION),
        ("Vaswani et al. (2017) introduced attention.", False, ClaimType.CITATION),
        ("Since 2019, self-supervision has dominated.", False, ClaimType.TEMPORAL),
        ("The system can solve arithmetic problems.", False, ClaimType.CAPABILITY),
        ("We observed that dropout stabilized training.", False, ClaimType.EMPIRICAL),
    ],
)
def test_single_category(text, has_refs, expected):
    assert categorize(text, has_citation_refs=has_refs) == expected


def test_citation_wins_when_ref_ids_passed_even_with_numbers():
    """If the claim references a paper, CITATION wins over STATISTICAL."""
    assert (
        categorize("Prior work reported 94% accuracy.", has_citation_refs=True)
        == ClaimType.CITATION
    )


def test_statistical_fallback_needs_cue():
    """A bare number without a measurement cue stays EMPIRICAL."""
    # "3 layers" is structural, not a statistical result.
    assert categorize("We used 3 layers.", has_citation_refs=False) == ClaimType.EMPIRICAL
    # Adding a cue flips it.
    assert (
        categorize("We reduced loss to 3.14 on the test set.", has_citation_refs=False)
        == ClaimType.STATISTICAL
    )


def test_p_value_pattern_is_statistical():
    assert (
        categorize("The gain is significant (p<0.01).", has_citation_refs=False)
        == ClaimType.STATISTICAL
    )
