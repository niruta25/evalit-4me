"""Smoke tests for the shipped venue configs — arxiv, ieee, neurips.

Each shipped YAML must:
  1. Load + validate against the full `VenueConfig` schema.
  2. Declare at least 1 rubric dimension with positive weight + max.
  3. Declare at least 5 required_sections alias groups (sanity floor).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalit_4me.config import VenueConfig, load_venue_config

CONFIGS_DIR = Path(__file__).parents[2] / "configs"


@pytest.mark.parametrize("name", ["neurips", "arxiv", "ieee"])
def test_shipped_config_loads(name: str) -> None:
    cfg = load_venue_config(CONFIGS_DIR / f"{name}.yaml")
    assert isinstance(cfg, VenueConfig)
    assert cfg.venue == name


@pytest.mark.parametrize("name", ["neurips", "arxiv", "ieee"])
def test_shipped_config_has_rubric_dimensions(name: str) -> None:
    cfg = load_venue_config(CONFIGS_DIR / f"{name}.yaml")
    assert len(cfg.rubric.dimensions) >= 1
    for d in cfg.rubric.dimensions:
        assert d.weight > 0
        assert d.max_score > 0


@pytest.mark.parametrize("name", ["neurips", "arxiv", "ieee"])
def test_shipped_config_has_required_sections(name: str) -> None:
    cfg = load_venue_config(CONFIGS_DIR / f"{name}.yaml")
    assert len(cfg.compliance.required_sections) >= 5


def test_arxiv_is_lenient() -> None:
    """arxiv.yaml must NOT require ethics or anonymization."""
    cfg = load_venue_config(CONFIGS_DIR / "arxiv.yaml")
    assert cfg.compliance.require_ethics is False
    assert cfg.compliance.require_anonymization is False


def test_ieee_single_blind() -> None:
    """IEEE is typically single-blind; anonymization must NOT be required."""
    cfg = load_venue_config(CONFIGS_DIR / "ieee.yaml")
    assert cfg.compliance.require_anonymization is False


def test_ieee_uses_5_point_scale() -> None:
    """IEEE rubric uses 0-5 per dimension."""
    cfg = load_venue_config(CONFIGS_DIR / "ieee.yaml")
    for d in cfg.rubric.dimensions:
        assert d.max_score == 5


def test_neurips_uses_4_point_scale() -> None:
    """NeurIPS rubric uses 0-4 per dimension (baseline regression pin)."""
    cfg = load_venue_config(CONFIGS_DIR / "neurips.yaml")
    for d in cfg.rubric.dimensions:
        assert d.max_score == 4


def test_arxiv_allows_longer_papers() -> None:
    """arxiv ceiling must exceed IEEE and NeurIPS ceilings."""
    arxiv = load_venue_config(CONFIGS_DIR / "arxiv.yaml").compliance
    ieee = load_venue_config(CONFIGS_DIR / "ieee.yaml").compliance
    neurips = load_venue_config(CONFIGS_DIR / "neurips.yaml").compliance
    assert arxiv.word_count_max is not None
    assert ieee.word_count_max is not None
    assert neurips.word_count_max is not None
    assert arxiv.word_count_max > ieee.word_count_max
    assert arxiv.word_count_max >= neurips.word_count_max
