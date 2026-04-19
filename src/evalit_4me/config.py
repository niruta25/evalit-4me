"""Canonical Pydantic schema for venue config files.

A venue config has two blocks — `compliance` (owned by Chunk 1.4) and
`rubric` (owned by this chunk). Chunk 1.4's `ComplianceConfig` is reused
here rather than redefined, so compliance-stage behavior stays keyed off
a single source of truth.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from evalit_4me.stages.compliance import ComplianceConfig


class RubricDimension(BaseModel):
    """One scoring dimension. `max_score` is in the venue's native scale
    (e.g., 4 for NeurIPS soundness). `weight` is the mixing weight when
    computing the overall total; weights may or may not sum to 1 — we
    normalize at score time so either convention works."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    weight: float = Field(gt=0.0)
    max_score: float = Field(gt=0.0)
    description: str = Field(default="", max_length=2000)


class BiasAdjustment(BaseModel):
    """Length/position bias knobs. Plan calls out these two sources."""

    model_config = ConfigDict(extra="forbid")

    enable_length_adjustment: bool = True
    # Word count above `length_penalty_start` starts penalizing; full
    # penalty of `max_penalty` is reached at `length_penalty_full`.
    length_penalty_start: int = 10000
    length_penalty_full: int = 20000
    max_penalty: float = 0.3

    @model_validator(mode="after")
    def _check_bounds(self) -> BiasAdjustment:
        if self.length_penalty_full <= self.length_penalty_start:
            raise ValueError("length_penalty_full must exceed length_penalty_start")
        if not 0.0 <= self.max_penalty <= 1.0:
            raise ValueError("max_penalty must be in [0, 1]")
        return self


class RubricConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    dimensions: list[RubricDimension] = Field(min_length=1)
    bias_adjustment: BiasAdjustment = Field(default_factory=BiasAdjustment)


# Keys a ScoringConfig.weights dict must carry. If you add a new stage
# subscore to `stages/scoring.py`, add the key here.
SCORING_KEYS = ("compliance", "verification", "depth", "rubric")


def _default_weights() -> dict[str, float]:
    return {
        "compliance": 0.15,
        "verification": 0.20,
        "depth": 0.20,
        "rubric": 0.45,
    }


class ScoringConfig(BaseModel):
    """Weights for the 5-stage composite overall score.

    Each weight is applied to a per-stage subscore in [0, 1] (see
    `stages/scoring.py`). When a stage is skipped (e.g., Stage 2 when
    no LLM is available), its weight redistributes across the present
    stages at composite time.
    """

    model_config = ConfigDict(extra="forbid")

    weights: dict[str, float] = Field(default_factory=_default_weights)

    @model_validator(mode="after")
    def _check_weights(self) -> ScoringConfig:
        for k in SCORING_KEYS:
            if k not in self.weights:
                raise ValueError(f"weights must include key {k!r}")
            if self.weights[k] < 0:
                raise ValueError(f"weight for {k!r} must be >= 0")
        extras = set(self.weights) - set(SCORING_KEYS)
        if extras:
            raise ValueError(f"unknown weight keys: {sorted(extras)}")
        if sum(self.weights.values()) <= 0:
            raise ValueError("at least one weight must be > 0")
        return self


class VenueConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    venue: str = Field(min_length=1)
    compliance: ComplianceConfig
    rubric: RubricConfig
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)


def load_venue_config(path: Path | str) -> VenueConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return VenueConfig.model_validate(raw)
