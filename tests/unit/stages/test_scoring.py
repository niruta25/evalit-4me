"""Composite 5-stage scoring tests.

Covers: per-stage subscore formulas, weight renormalization when stages
are skipped, weight validation, and warning-banner behavior.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from evalit_4me.config import ScoringConfig
from evalit_4me.contracts import (
    ClaimLedger,
    ComplianceCheck,
    ComplianceReport,
    DepthReport,
    DimensionScore,
    EvaluationRecord,
    Paper,
    PaperMetadata,
    Provenance,
    RubricScores,
    Triage,
)
from evalit_4me.stages.scoring import composite_score

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _compliance(
    pass_count: int, fail_count: int = 0, triage: Triage = Triage.PASS
) -> ComplianceReport:
    checks = [ComplianceCheck(name=f"c{i}", passed=True) for i in range(pass_count)]
    checks += [ComplianceCheck(name=f"f{i}", passed=False) for i in range(fail_count)]
    return ComplianceReport(
        triage=triage,
        section_checks=checks,
        format_checks=[],
        issues=[] if triage == Triage.PASS else ["something"],
    )


def _ledger(total: int = 10, verified: int = 0, halluc: int = 0) -> ClaimLedger:
    return ClaimLedger(
        claims=[],
        results=[],
        total_claims=total,
        verified_count=verified,
        hallucination_count=halluc,
        mean_confidence=0.0,
    )


def _depth(scores: tuple[float, float, float, float] = (0.8, 0.7, 0.6, 0.9)) -> DepthReport:
    meth, lim, repro, logic = scores
    return DepthReport(
        methodology_score=meth,
        limitations_score=lim,
        reproducibility_score=repro,
        logical_soundness_score=logic,
        rationales={},
    )


def _rubric(total: float = 0.6) -> RubricScores:
    return RubricScores(
        rubric_id="test",
        dimensions=[DimensionScore(name="x", score=total * 4, max_score=4)],
        raw_total=total,
        bias_adjusted_total=total,
        adjustment_notes=[],
    )


def _record(
    *,
    compliance: ComplianceReport | None = None,
    ledger: ClaimLedger | None = None,
    depth: DepthReport | None = None,
    rubric: RubricScores | None = None,
) -> EvaluationRecord:
    return EvaluationRecord(
        paper=Paper(id="p", metadata=PaperMetadata(title="t")),
        compliance=compliance or _compliance(pass_count=5),
        claims=ledger or _ledger(),
        depth=depth if depth is not None else _depth(),
        rubric=rubric if rubric is not None else _rubric(),
        provenance=Provenance(evalit_version="0.0.1", config_hash="x"),
    )


# ---------------------------------------------------------------------------
# Subscore formulas
# ---------------------------------------------------------------------------


def test_compliance_subscore_is_pass_rate():
    # 4 passed / 6 total = 0.667
    rec = _record(compliance=_compliance(pass_count=4, fail_count=2))
    cs = composite_score(rec)
    comp = {s.name: s.value for s in cs.subscores}
    score = comp["compliance"]
    assert score is not None
    assert abs(score - 0.6667) < 1e-3


def test_verification_subscore_uses_hallucinations():
    # 10 claims, 2 hallucinations -> 1 - 0.2 = 0.8
    rec = _record(ledger=_ledger(total=10, halluc=2))
    cs = composite_score(rec)
    comp = {s.name: s.value for s in cs.subscores}
    assert comp["verification"] == pytest.approx(0.8)


def test_verification_subscore_is_none_when_no_claims():
    rec = _record(ledger=_ledger(total=0))
    cs = composite_score(rec)
    comp = {s.name: s.value for s in cs.subscores}
    assert comp["verification"] is None


def test_depth_subscore_is_mean():
    rec = _record(depth=_depth((0.8, 0.6, 0.4, 0.2)))
    cs = composite_score(rec)
    comp = {s.name: s.value for s in cs.subscores}
    assert comp["depth"] == pytest.approx(0.5)


def test_rubric_subscore_pulls_bias_adjusted():
    rec = _record(rubric=_rubric(total=0.72))
    cs = composite_score(rec)
    comp = {s.name: s.value for s in cs.subscores}
    assert comp["rubric"] == pytest.approx(0.72)


# ---------------------------------------------------------------------------
# Weighted composition
# ---------------------------------------------------------------------------


def test_all_stages_present_default_weights():
    # compliance=1.0, verification=1.0, depth=0.75, rubric=0.6
    rec = _record(
        compliance=_compliance(pass_count=5),
        ledger=_ledger(total=10, halluc=0),
        depth=_depth((0.75, 0.75, 0.75, 0.75)),
        rubric=_rubric(total=0.6),
    )
    cs = composite_score(rec)
    # composite = 0.15*1 + 0.20*1 + 0.20*0.75 + 0.45*0.6 = 0.15 + 0.20 + 0.15 + 0.27 = 0.77
    assert cs.composite == pytest.approx(0.77, abs=0.001)


def test_verification_none_redistributes_weight():
    """When verification is None, its 0.20 weight redistributes across the
    other three stages (which together have total weight 0.80)."""
    rec = _record(
        compliance=_compliance(pass_count=5),
        ledger=_ledger(total=0),  # verification -> None
        depth=_depth((0.75, 0.75, 0.75, 0.75)),
        rubric=_rubric(total=0.6),
    )
    cs = composite_score(rec)
    # present weights: 0.15 + 0.20 + 0.45 = 0.80
    # contributions: (0.15*1 + 0.20*0.75 + 0.45*0.6) / 0.80
    # = (0.15 + 0.15 + 0.27) / 0.80 = 0.5700 / 0.80 = 0.7125
    assert cs.composite == pytest.approx(0.7125, abs=0.001)


def test_custom_weights_from_config():
    cfg = ScoringConfig(
        weights={"compliance": 0.10, "verification": 0.10, "depth": 0.30, "rubric": 0.50}
    )
    rec = _record(
        compliance=_compliance(pass_count=5),
        ledger=_ledger(total=10, halluc=0),
        depth=_depth((0.5, 0.5, 0.5, 0.5)),
        rubric=_rubric(total=1.0),
    )
    cs = composite_score(rec, cfg)
    # 0.10*1 + 0.10*1 + 0.30*0.5 + 0.50*1 = 0.10 + 0.10 + 0.15 + 0.50 = 0.85
    assert cs.composite == pytest.approx(0.85, abs=0.001)


def test_breakdown_dict_matches_subscores():
    rec = _record(ledger=_ledger(total=0))  # verification None
    cs = composite_score(rec)
    breakdown = cs.breakdown()
    assert breakdown["verification"] is None
    assert set(breakdown.keys()) == {"compliance", "verification", "depth", "rubric"}


# ---------------------------------------------------------------------------
# Weight validation
# ---------------------------------------------------------------------------


def test_weights_rejects_negative():
    with pytest.raises(ValidationError):
        ScoringConfig.model_validate(
            {"weights": {"compliance": -0.1, "verification": 0.2, "depth": 0.2, "rubric": 0.45}}
        )


def test_weights_rejects_missing_key():
    with pytest.raises(ValidationError):
        ScoringConfig.model_validate(
            {"weights": {"compliance": 0.15, "verification": 0.2, "depth": 0.2}}  # no rubric
        )


def test_weights_rejects_extra_key():
    with pytest.raises(ValidationError):
        ScoringConfig.model_validate(
            {
                "weights": {
                    "compliance": 0.15,
                    "verification": 0.2,
                    "depth": 0.2,
                    "rubric": 0.45,
                    "mystery": 0.1,
                }
            }
        )


def test_weights_rejects_all_zero():
    with pytest.raises(ValidationError):
        ScoringConfig.model_validate(
            {"weights": {"compliance": 0.0, "verification": 0.0, "depth": 0.0, "rubric": 0.0}}
        )


# ---------------------------------------------------------------------------
# Warning banner
# ---------------------------------------------------------------------------


def test_no_banner_on_pass():
    rec = _record(compliance=_compliance(pass_count=5, triage=Triage.PASS))
    cs = composite_score(rec)
    assert cs.warning_banner is None


def test_banner_on_conditional():
    rec = _record(compliance=_compliance(pass_count=4, fail_count=1, triage=Triage.CONDITIONAL))
    cs = composite_score(rec)
    assert cs.warning_banner is not None
    assert "CONDITIONAL" in cs.warning_banner


def test_banner_on_fail():
    rec = _record(compliance=_compliance(pass_count=3, fail_count=2, triage=Triage.FAIL))
    cs = composite_score(rec)
    assert cs.warning_banner is not None
    assert "FAIL" in cs.warning_banner


# ---------------------------------------------------------------------------
# Regression pin: Shumailov-style "compliance FAIL but strong rubric" flow
# ---------------------------------------------------------------------------


def test_fail_triage_does_not_zero_out_composite():
    """Regression pin for the Shumailov bug: a paper that triages FAIL but
    has strong depth + rubric should still score reasonably, with a banner."""
    rec = _record(
        compliance=_compliance(pass_count=5, fail_count=2, triage=Triage.FAIL),
        ledger=_ledger(total=0),
        depth=_depth((0.80, 1.00, 0.25, 0.75)),
        rubric=_rubric(total=0.64),
    )
    cs = composite_score(rec)
    # compliance = 5/7 ≈ 0.714; depth mean = 0.70; rubric = 0.64; verification = None
    # present weight = 0.15 + 0.20 + 0.45 = 0.80
    # composite = (0.15*0.714 + 0.20*0.70 + 0.45*0.64) / 0.80 ≈ 0.667
    assert cs.composite > 0.6, f"expected composite > 0.6, got {cs.composite}"
    assert cs.warning_banner is not None
