"""Severity mapping: base table + CRITICAL escalation on superlatives."""

from __future__ import annotations

from evalit_4me.contracts import Claim, ClaimType, Severity, SourceSpan
from evalit_4me.stages.claims.severity import assign_severity


def _claim(text: str, claim_type: ClaimType) -> Claim:
    return Claim(
        id="c",
        text=text,
        claim_type=claim_type,
        severity=Severity.LOW,
        source_span=SourceSpan(section_id="s", char_start=0, char_end=1),
    )


def test_base_mapping():
    assert assign_severity(_claim("x", ClaimType.CITATION)) == Severity.HIGH
    assert assign_severity(_claim("x", ClaimType.STATISTICAL)) == Severity.HIGH
    assert assign_severity(_claim("x", ClaimType.CAPABILITY)) == Severity.MEDIUM
    assert assign_severity(_claim("x", ClaimType.EMPIRICAL)) == Severity.MEDIUM
    assert assign_severity(_claim("x", ClaimType.TEMPORAL)) == Severity.LOW


def test_critical_escalation_on_sota():
    c = _claim("Our approach is state-of-the-art on the benchmark.", ClaimType.STATISTICAL)
    assert assign_severity(c) == Severity.CRITICAL


def test_critical_escalation_on_first_to():
    c = _claim("We are the first to demonstrate this result.", ClaimType.CITATION)
    assert assign_severity(c) == Severity.CRITICAL


def test_critical_does_not_apply_to_non_high_base():
    """A 'novel' CAPABILITY claim stays MEDIUM — escalation only applies
    when the base is HIGH (i.e. citation or statistical)."""
    c = _claim("A novel approach that can solve it.", ClaimType.CAPABILITY)
    assert assign_severity(c) == Severity.MEDIUM
