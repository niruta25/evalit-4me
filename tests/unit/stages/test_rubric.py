"""Rubric scorer tests — schema loading, heuristic path, LLM path, bias, init."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import ValidationError

from evalit_4me.config import (
    BiasAdjustment,
    RubricConfig,
    RubricDimension,
    VenueConfig,
    load_venue_config,
)
from evalit_4me.contracts import ClaimLedger, DepthReport, Paper, PaperMetadata, Section
from evalit_4me.llm.protocol import EmbedRequest, EmbedResponse, LLMRequest, LLMResponse
from evalit_4me.stages.rubric import init_template, score_rubric, validate_config_file

CONFIGS_DIR = Path(__file__).parents[3] / "configs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_rubric_config() -> RubricConfig:
    return RubricConfig(
        id="test-rubric",
        dimensions=[
            RubricDimension(name="soundness", weight=0.4, max_score=4, description="..."),
            RubricDimension(name="presentation", weight=0.3, max_score=4, description="..."),
            RubricDimension(name="contribution", weight=0.3, max_score=4, description="..."),
        ],
        bias_adjustment=BiasAdjustment(),
    )


def _paper(word_count: int = 5000) -> Paper:
    body = " ".join(["word"] * word_count)
    return Paper(
        id="p",
        metadata=PaperMetadata(title="Test", abstract="An abstract."),
        sections=[
            Section(id="intro", title="Introduction", text=body, order=0),
            Section(id="method", title="Method", text=body, order=1),
            Section(id="results", title="Results", text=body, order=2),
            Section(id="conclusion", title="Conclusion", text=body, order=3),
        ],
    )


def _ledger(verified: int = 4, total: int = 5, halluc: int = 0) -> ClaimLedger:
    return ClaimLedger(
        claims=[],
        results=[],
        total_claims=total,
        verified_count=verified,
        hallucination_count=halluc,
        mean_confidence=0.8,
    )


def _depth() -> DepthReport:
    return DepthReport(
        methodology_score=0.8,
        limitations_score=0.6,
        reproducibility_score=0.5,
        logical_soundness_score=0.9,
        rationales={},
    )


@dataclass
class ScriptedLLM:
    name: str = "scripted"
    script: dict[str, str] = field(default_factory=dict)
    default: str = '{"score": 3.0, "rationale": "default"}'

    def complete(self, request: LLMRequest) -> LLMResponse:
        text = self.default
        for cue, resp in self.script.items():
            if cue in request.prompt:
                text = resp
                break
        return LLMResponse(
            text=text,
            model=request.model,
            provider=self.name,
            prompt_tokens=max(1, len(request.prompt) // 4),
            completion_tokens=max(1, len(text) // 4),
        )

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        return EmbedResponse(
            vectors=[[0.0] * 4 for _ in request.texts],
            model=request.model,
            provider=self.name,
        )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_real_neurips_yaml_loads_full_config():
    cfg = load_venue_config(CONFIGS_DIR / "neurips.yaml")
    assert cfg.venue == "neurips"
    # Compliance block still there (inherited from Chunk 1.4).
    assert cfg.compliance.require_anonymization is True
    # Rubric block present.
    assert cfg.rubric.id == "neurips-reviewer-v1"
    dim_names = {d.name for d in cfg.rubric.dimensions}
    assert dim_names == {"soundness", "presentation", "contribution", "significance"}


def test_template_yaml_is_valid_config():
    """`evalit rubric init` scaffolds a valid custom config."""
    cfg = load_venue_config(CONFIGS_DIR / "template.yaml")
    assert cfg.rubric.dimensions  # non-empty
    for d in cfg.rubric.dimensions:
        assert d.max_score > 0
        assert d.weight > 0


def test_config_rejects_extra_fields():
    with pytest.raises(ValidationError):
        VenueConfig.model_validate(
            {
                "venue": "x",
                "mystery": 1,
                "compliance": {},
                "rubric": {
                    "id": "r",
                    "dimensions": [{"name": "s", "weight": 1.0, "max_score": 4}],
                },
            }
        )


def test_rubric_requires_at_least_one_dimension():
    with pytest.raises(ValidationError):
        RubricConfig.model_validate({"id": "r", "dimensions": []})


def test_bias_adjustment_validates_bounds():
    with pytest.raises(ValidationError):
        BiasAdjustment.model_validate({"length_penalty_start": 10000, "length_penalty_full": 5000})


def test_validate_config_file_returns_venue_config(tmp_path: Path):
    cfg = validate_config_file(CONFIGS_DIR / "neurips.yaml")
    assert isinstance(cfg, VenueConfig)


# ---------------------------------------------------------------------------
# Heuristic scoring
# ---------------------------------------------------------------------------


def test_heuristic_produces_sensible_scores():
    rubric = _minimal_rubric_config()
    result = score_rubric(_paper(), _ledger(), _depth(), rubric, provider=None)
    assert result.rubric_id == "test-rubric"
    assert len(result.dimensions) == 3
    # Every dimension within [0, max_score].
    for dim in result.dimensions:
        assert 0.0 <= dim.score <= dim.max_score
    # raw_total should be in 0..1 (normalized fraction of max).
    assert 0.0 <= result.raw_total <= 1.0


def test_heuristic_penalizes_hallucinations():
    rubric = _minimal_rubric_config()
    clean = score_rubric(_paper(), _ledger(halluc=0), _depth(), rubric, provider=None)
    dirty = score_rubric(_paper(), _ledger(halluc=3), _depth(), rubric, provider=None)
    soundness_clean = next(d for d in clean.dimensions if d.name == "soundness").score
    soundness_dirty = next(d for d in dirty.dimensions if d.name == "soundness").score
    assert soundness_dirty < soundness_clean


def test_heuristic_neutral_on_unknown_dimension():
    rubric = RubricConfig(
        id="r",
        dimensions=[RubricDimension(name="mystery-dim", weight=1.0, max_score=4)],
    )
    result = score_rubric(_paper(), _ledger(), _depth(), rubric, provider=None)
    assert result.dimensions[0].score == pytest.approx(2.0, abs=0.01)  # 0.5 * 4


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------


def test_llm_path_parses_score_and_rationale():
    rubric = _minimal_rubric_config()
    provider = ScriptedLLM(default='{"score": 3.5, "rationale": "LLM says so."}')
    result = score_rubric(_paper(), _ledger(), _depth(), rubric, provider=provider)
    assert all(d.score == 3.5 for d in result.dimensions)
    assert all(d.rationale == "LLM says so." for d in result.dimensions)


def test_llm_score_clamped_to_max():
    rubric = _minimal_rubric_config()
    provider = ScriptedLLM(default='{"score": 99, "rationale": "overshoot"}')
    result = score_rubric(_paper(), _ledger(), _depth(), rubric, provider=provider)
    # max_score on each dimension is 4.
    for d in result.dimensions:
        assert d.score == 4.0


def test_llm_malformed_falls_back_to_heuristic():
    rubric = _minimal_rubric_config()
    provider = ScriptedLLM(default="not json")
    result = score_rubric(_paper(), _ledger(), _depth(), rubric, provider=provider)
    assert all("LLM output unparseable" in (d.rationale or "") for d in result.dimensions)


# ---------------------------------------------------------------------------
# Bias adjustment
# ---------------------------------------------------------------------------


def test_no_penalty_when_under_length_threshold():
    rubric = RubricConfig(
        id="r",
        dimensions=[RubricDimension(name="soundness", weight=1.0, max_score=4)],
        bias_adjustment=BiasAdjustment(
            length_penalty_start=10000, length_penalty_full=20000, max_penalty=0.3
        ),
    )
    result = score_rubric(_paper(word_count=1000), _ledger(), _depth(), rubric, provider=None)
    assert result.raw_total == result.bias_adjusted_total
    assert result.adjustment_notes == []


def test_penalty_applied_when_over_threshold():
    rubric = RubricConfig(
        id="r",
        dimensions=[RubricDimension(name="soundness", weight=1.0, max_score=4)],
        bias_adjustment=BiasAdjustment(
            length_penalty_start=1000, length_penalty_full=2000, max_penalty=0.3
        ),
    )
    # 5000 words >> 2000 threshold -> full penalty of 0.3.
    result = score_rubric(_paper(word_count=5000), _ledger(), _depth(), rubric, provider=None)
    assert result.bias_adjusted_total < result.raw_total
    assert abs(result.raw_total - result.bias_adjusted_total - 0.3) < 1e-6
    assert len(result.adjustment_notes) == 1


def test_bias_adjustment_disabled():
    rubric = RubricConfig(
        id="r",
        dimensions=[RubricDimension(name="soundness", weight=1.0, max_score=4)],
        bias_adjustment=BiasAdjustment(enable_length_adjustment=False),
    )
    result = score_rubric(_paper(word_count=50000), _ledger(), _depth(), rubric, provider=None)
    assert result.bias_adjusted_total == result.raw_total
    assert result.adjustment_notes == []


# ---------------------------------------------------------------------------
# evalit rubric init
# ---------------------------------------------------------------------------


def test_init_template_creates_valid_file(tmp_path: Path):
    target = tmp_path / "custom.yaml"
    out = init_template(target)
    assert out == target
    assert target.exists()
    # Scaffolded file must validate.
    cfg = load_venue_config(target)
    assert cfg.venue  # populated


def test_init_template_refuses_existing_without_overwrite(tmp_path: Path):
    target = tmp_path / "existing.yaml"
    target.write_text("existing")
    with pytest.raises(FileExistsError):
        init_template(target)


def test_init_template_overwrites_when_requested(tmp_path: Path):
    target = tmp_path / "existing.yaml"
    target.write_text("existing")
    init_template(target, overwrite=True)
    assert "rubric" in target.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixture-paper smoke: scoring runs on 3+ fixtures
# ---------------------------------------------------------------------------


def test_scores_in_expected_ranges_on_fixtures():
    """Exit gate: scores in expected ranges for fixtures."""
    from evalit_4me.ingest.parser import parse_markdown

    cfg = load_venue_config(CONFIGS_DIR / "neurips.yaml")
    fixtures_dir = Path(__file__).parents[2] / "fixtures" / "markdown"
    md_files = sorted(fixtures_dir.glob("*.md"))
    assert len(md_files) >= 3
    for md in md_files[:3]:
        paper = parse_markdown(md.read_text(encoding="utf-8"), source_name=md.stem)
        result = score_rubric(paper, _ledger(verified=0, total=0), _depth(), cfg, provider=None)
        # Every raw dimension score sits inside its declared max.
        for dim in result.dimensions:
            assert 0.0 <= dim.score <= dim.max_score
        # Weighted total is a normalized fraction.
        assert 0.0 <= result.raw_total <= 1.0
        assert 0.0 <= result.bias_adjusted_total <= 1.0
