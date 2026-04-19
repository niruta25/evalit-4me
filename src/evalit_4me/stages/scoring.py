"""Stage-5 companion: composite 5-stage weighted overall score.

Replaces the prior "use rubric as the sole overall score + hard
compliance-FAIL override" logic with a weighted composite over four
per-stage subscores:

    compliance    = passed_checks / total_checks
    verification  = max(0, 1 - hallucinations / total_claims)   or None
    depth         = mean of the 4 depth-dimension scores
    rubric        = rubric.bias_adjusted_total

When a subscore is `None` (e.g., verification when no claims exist),
its weight redistributes across the present subscores so the composite
stays in [0, 1] regardless of which stages ran.

Design docs: `.reports/2026-04-18-composite-score-plan.md`.
"""

from __future__ import annotations

from dataclasses import dataclass

from evalit_4me.config import SCORING_KEYS, ScoringConfig, VenueConfig
from evalit_4me.contracts import EvaluationRecord, Triage


@dataclass(frozen=True)
class SubScore:
    """One stage's contribution to the composite."""

    name: str
    value: float | None
    weight: float
    # `contribution` is `value * (weight / total_present_weight)` when value
    # is not None, else 0. Summing contributions gives the composite.
    contribution: float


@dataclass(frozen=True)
class CompositeScore:
    composite: float  # in [0, 1]
    subscores: list[SubScore]
    warning_banner: str | None  # non-None when compliance triage != PASS

    def breakdown(self) -> dict[str, float | None]:
        """Dict suitable for `ReviewDraft.composite_breakdown`."""
        return {s.name: s.value for s in self.subscores}


def composite_score(
    record: EvaluationRecord,
    config: VenueConfig | ScoringConfig | None = None,
) -> CompositeScore:
    """Compute the weighted composite and the banner text."""
    scoring = _resolve_scoring(config)
    values = _compute_subscore_values(record)
    composite, subscores = _weighted(values, scoring.weights)
    banner = _warning_banner(record)
    return CompositeScore(
        composite=round(composite, 4),
        subscores=subscores,
        warning_banner=banner,
    )


# ---------------------------------------------------------------------------
# Per-stage subscore calculation
# ---------------------------------------------------------------------------


def _compute_subscore_values(record: EvaluationRecord) -> dict[str, float | None]:
    return {
        "compliance": _compliance_score(record),
        "verification": _verification_score(record),
        "depth": _depth_score(record),
        "rubric": _rubric_score(record),
    }


def _compliance_score(record: EvaluationRecord) -> float:
    """Pass rate over `section_checks` + `format_checks`. No triage enum."""
    checks = list(record.compliance.section_checks) + list(record.compliance.format_checks)
    if not checks:
        return 1.0  # nothing to check -> neutral-high
    passed = sum(1 for c in checks if c.passed)
    return passed / len(checks)


def _verification_score(record: EvaluationRecord) -> float | None:
    """1 - (hallucinations / total_claims) when we have claims; else None.

    Returning None signals "no signal" rather than "bad signal" — callers
    redistribute this stage's weight.
    """
    total = record.claims.total_claims
    if total <= 0:
        return None
    return max(0.0, 1.0 - record.claims.hallucination_count / total)


def _depth_score(record: EvaluationRecord) -> float | None:
    if record.depth is None:
        return None
    d = record.depth
    return (
        d.methodology_score
        + d.limitations_score
        + d.reproducibility_score
        + d.logical_soundness_score
    ) / 4.0


def _rubric_score(record: EvaluationRecord) -> float | None:
    if record.rubric is None:
        return None
    return record.rubric.bias_adjusted_total


# ---------------------------------------------------------------------------
# Weight resolution + weighted sum
# ---------------------------------------------------------------------------


def _resolve_scoring(config: VenueConfig | ScoringConfig | None) -> ScoringConfig:
    if config is None:
        return ScoringConfig()
    if isinstance(config, ScoringConfig):
        return config
    return config.scoring


def _weighted(
    values: dict[str, float | None], weights: dict[str, float]
) -> tuple[float, list[SubScore]]:
    """Return (composite, subscores). Absent subscores don't distort the total."""
    present_weight_total = sum(weights[k] for k in SCORING_KEYS if values.get(k) is not None)
    if present_weight_total <= 0:
        # No stage contributed — composite is 0 by construction.
        return 0.0, [
            SubScore(name=k, value=values.get(k), weight=weights[k], contribution=0.0)
            for k in SCORING_KEYS
        ]

    composite = 0.0
    subs: list[SubScore] = []
    for k in SCORING_KEYS:
        v = values.get(k)
        if v is None:
            subs.append(SubScore(name=k, value=None, weight=weights[k], contribution=0.0))
            continue
        contribution = v * (weights[k] / present_weight_total)
        composite += contribution
        subs.append(
            SubScore(
                name=k,
                value=round(v, 4),
                weight=weights[k],
                contribution=round(contribution, 4),
            )
        )
    return composite, subs


# ---------------------------------------------------------------------------
# Warning banner (surfaces compliance non-PASS without forcing rec)
# ---------------------------------------------------------------------------


def _warning_banner(record: EvaluationRecord) -> str | None:
    triage = record.compliance.triage
    if triage == Triage.PASS:
        return None
    issues = record.compliance.issues
    joined = "; ".join(issues) if issues else "see compliance section"
    return (
        f"⚠️  Compliance {triage.value}: {joined}. "
        "The composite score below does not force a recommendation — review these issues "
        "manually before accepting or rejecting."
    )
