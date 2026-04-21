"""Stage 4 — Rubric scorer.

Given a `Paper`, its `ClaimLedger` (from Stage 2), its `DepthReport`
(Stage 3), and a validated `VenueConfig`, produce a `RubricScores` object:
one `DimensionScore` per config dimension plus a raw total and a bias-
adjusted total.

Scoring paths:

* **LLM path** — one single call scores *all* rubric dimensions in one
  request. The prompt includes the paper abstract, short excerpts per
  key section, and the list of dimensions with their max scores and
  descriptions. The model returns one JSON object mapping each dimension
  name to `{"score": float, "rationale": str}`. Batching the call cuts
  the per-paper LLM budget from N calls to 1 — on a typical 4-dimension
  venue config that's a 4× reduction with no measurable quality loss
  (all dimensions share the same paper context anyway).
* **Heuristic fallback** — triggered when `provider is None`, when the
  LLM returns unparseable JSON, or on a per-dimension basis when the
  batched response is missing or malformed for that specific dimension.
  Scores are derived from the already-computed verification ledger +
  depth report + a dimension-specific baseline, so the pipeline always
  produces a usable `RubricScores` even in `--dry-run`.

Bias adjustment reduces the total by a fraction proportional to how far
`word_count` exceeds `length_penalty_start`, capped at `max_penalty`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from evalit_4me.config import (
    BiasAdjustment,
    RubricConfig,
    RubricDimension,
    VenueConfig,
    load_venue_config,
)
from evalit_4me.contracts import ClaimLedger, DepthReport, DimensionScore, Paper, RubricScores
from evalit_4me.llm.protocol import LLMProvider, LLMRequest

DEFAULT_MODEL = "claude-sonnet-4-6"

SCORE_SYSTEM = """You are an expert reviewer for a top-tier ML conference.
Score the paper on EACH of the rubric dimensions listed below. Follow these rules:
- Read every dimension description carefully.
- Return ONLY one JSON object. Each top-level key is a dimension name, and
  each value is an object with two keys: "score" (float in [0, max_score]
  for that dimension) and "rationale" (<= 2 sentences).
- Include every dimension from the list. Do NOT invent dimensions.
- Do NOT include any text outside the JSON.
"""

SCORE_USER = """Paper title: {title}

Abstract:
{abstract}

Key signals (from earlier pipeline stages):
- Total claims extracted: {claim_count}
- Verified claim fraction: {verified_fraction:.2f}
- Hallucination flag count: {hallucination_count}
- Mean verification confidence: {mean_confidence:.2f}
- Methodology score: {methodology:.2f}
- Limitations score: {limitations:.2f}
- Reproducibility score: {reproducibility:.2f}

Section excerpts (each truncated to 500 chars):
{excerpts}

Dimensions to score:
{dim_block}

Return the JSON now."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_rubric(
    paper: Paper,
    ledger: ClaimLedger,
    depth: DepthReport,
    config: VenueConfig | RubricConfig,
    *,
    provider: LLMProvider | None = None,
    model: str = DEFAULT_MODEL,
) -> RubricScores:
    rubric = config.rubric if isinstance(config, VenueConfig) else config
    adjustment = rubric.bias_adjustment
    signals = _collect_signals(ledger, depth)

    parsed: dict[str, tuple[float, str]] = {}
    if provider is not None:
        parsed = _llm_score_batch(
            paper=paper,
            signals=signals,
            dims=rubric.dimensions,
            provider=provider,
            model=model,
        )

    dim_scores: list[DimensionScore] = []
    for dim in rubric.dimensions:
        if dim.name in parsed:
            raw_score, rationale = parsed[dim.name]
            score = max(0.0, min(dim.max_score, raw_score))
        elif provider is None:
            score, rationale = _heuristic_score(dim, signals)
        else:
            score, rationale = _heuristic_score(dim, signals)
            rationale = f"{rationale} (LLM output unparseable; fell back to heuristics.)"
        dim_scores.append(
            DimensionScore(
                name=dim.name,
                score=round(score, 4),
                max_score=dim.max_score,
                rationale=rationale,
            )
        )

    raw_total = _weighted_total(dim_scores, rubric.dimensions)
    adjusted_total, adjustment_notes = _apply_bias_adjustment(raw_total, paper, adjustment)

    return RubricScores(
        rubric_id=rubric.id,
        dimensions=dim_scores,
        raw_total=round(raw_total, 4),
        bias_adjusted_total=round(adjusted_total, 4),
        adjustment_notes=adjustment_notes,
    )


def init_template(target: Path | str, *, overwrite: bool = False) -> Path:
    """Copy the shipped `configs/template.yaml` to `target`.

    This is the body of the `evalit rubric init` command. Chunk 1.13 will
    wire it up to Typer; for now it's a library entrypoint so tests can
    assert scaffolding behavior without a CLI surface.
    """
    dest = Path(target)
    if dest.exists() and not overwrite:
        raise FileExistsError(f"{dest} already exists; pass overwrite=True to replace.")
    # Wheel install: evalit_4me/_configs/template.yaml (parents[1] from this file).
    # Editable install: repo-root configs/template.yaml (parents[3]).
    pkg_local = Path(__file__).resolve().parents[1] / "_configs" / "template.yaml"
    template = (
        pkg_local
        if pkg_local.exists()
        else (Path(__file__).resolve().parents[3] / "configs" / "template.yaml")
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def validate_config_file(path: Path | str) -> VenueConfig:
    """Load + validate a venue YAML; raises Pydantic ValidationError on bad shapes."""
    return load_venue_config(path)


# ---------------------------------------------------------------------------
# Per-dimension scoring
# ---------------------------------------------------------------------------


@dataclass
class _Signals:
    claim_count: int
    verified_fraction: float
    hallucination_count: int
    mean_confidence: float
    methodology: float
    limitations: float
    reproducibility: float
    logical_soundness: float


def _collect_signals(ledger: ClaimLedger, depth: DepthReport) -> _Signals:
    total = ledger.total_claims or 0
    verified_fraction = ledger.verified_count / total if total > 0 else 0.0
    return _Signals(
        claim_count=total,
        verified_fraction=verified_fraction,
        hallucination_count=ledger.hallucination_count,
        mean_confidence=ledger.mean_confidence,
        methodology=depth.methodology_score,
        limitations=depth.limitations_score,
        reproducibility=depth.reproducibility_score,
        logical_soundness=depth.logical_soundness_score,
    )


def _heuristic_score(dim: RubricDimension, signals: _Signals) -> tuple[float, str]:
    """Produce a dimension score from already-computed pipeline signals.

    Each canonical dimension is mapped to the signals that most directly
    reflect it. Unknown dimension names fall back to a neutral 0.5 * max.
    """
    name = dim.name.lower()
    if "sound" in name:
        # Soundness: verified fraction, hallucination penalty, methodology score.
        base = (
            0.5 * signals.verified_fraction
            + 0.3 * signals.methodology
            + 0.2
            * (
                1.0
                if signals.hallucination_count == 0
                else max(0.0, 1.0 - 0.2 * signals.hallucination_count)
            )
        )
        rationale = (
            f"Heuristic: verified={signals.verified_fraction:.2f}, "
            f"methodology={signals.methodology:.2f}, "
            f"hallucinations={signals.hallucination_count}."
        )
    elif "present" in name or "clarity" in name:
        base = 0.6 * signals.logical_soundness + 0.4 * signals.limitations
        rationale = (
            f"Heuristic: logical_soundness={signals.logical_soundness:.2f}, "
            f"limitations={signals.limitations:.2f}."
        )
    elif "contribution" in name or "original" in name:
        base = 0.5 * signals.methodology + 0.5 * signals.reproducibility
        rationale = (
            f"Heuristic: methodology={signals.methodology:.2f}, "
            f"reproducibility={signals.reproducibility:.2f}."
        )
    elif "significance" in name or "impact" in name:
        base = (
            0.5 * signals.methodology + 0.3 * signals.logical_soundness + 0.2 * signals.limitations
        )
        rationale = (
            f"Heuristic: methodology={signals.methodology:.2f}, "
            f"logical={signals.logical_soundness:.2f}, "
            f"limitations={signals.limitations:.2f}."
        )
    else:
        base = 0.5
        rationale = f"Heuristic: unknown dimension {dim.name!r}; defaulting to neutral 0.5."
    score = max(0.0, min(1.0, base)) * dim.max_score
    return score, rationale


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _llm_score_batch(
    *,
    paper: Paper,
    signals: _Signals,
    dims: list[RubricDimension],
    provider: LLMProvider,
    model: str,
) -> dict[str, tuple[float, str]]:
    """Score every dimension in one LLM call.

    Returns a dict keyed by dimension name. Dimensions whose score couldn't
    be parsed are simply absent from the dict, letting the caller fall back
    to heuristics on a per-dimension basis.
    """
    excerpts = _build_excerpts(paper)
    dim_block = "\n".join(
        f'- "{dim.name}" (max {dim.max_score}): {dim.description or "(no description)"}'
        for dim in dims
    )
    request = LLMRequest(
        prompt=SCORE_USER.format(
            title=paper.metadata.title or "(untitled)",
            abstract=(paper.metadata.abstract or "")[:1500],
            claim_count=signals.claim_count,
            verified_fraction=signals.verified_fraction,
            hallucination_count=signals.hallucination_count,
            mean_confidence=signals.mean_confidence,
            methodology=signals.methodology,
            limitations=signals.limitations,
            reproducibility=signals.reproducibility,
            excerpts=excerpts,
            dim_block=dim_block,
        ),
        system=SCORE_SYSTEM,
        model=model,
        temperature=0.0,
        # ~160 tokens per dimension is comfortable for a score + 2-sentence
        # rationale; scale with the number of dimensions plus headroom.
        max_tokens=max(512, 200 * len(dims)),
        seed=0,
    )
    response = provider.complete(request)
    return _parse_batched_json(response.text, dims)


def _build_excerpts(paper: Paper) -> str:
    keep = ("introduction", "method", "results", "conclusion", "limitations", "discussion")
    parts: list[str] = []
    for section in paper.sections:
        title = section.title.strip().lower()
        if any(k in title for k in keep):
            snippet = section.text[:500].replace("\n", " ")
            parts.append(f"### {section.title}\n{snippet}")
    return "\n\n".join(parts) if parts else "(no key sections found)"


def _parse_batched_json(
    raw: str, dims: list[RubricDimension]
) -> dict[str, tuple[float, str]]:
    """Parse the batched rubric response.

    Shape expected: `{dim_name: {"score": float, "rationale": str}, ...}`.
    Any dimension whose entry is missing or malformed is simply omitted —
    the caller applies a heuristic fallback for those.
    """
    candidate = _FENCE_RE.sub("", raw).strip()
    if not candidate:
        return {}
    obj: dict | None = None
    try:
        loaded = json.loads(candidate)
        if isinstance(loaded, dict):
            obj = loaded
    except json.JSONDecodeError:
        m = _JSON_OBJ_RE.search(candidate)
        if m:
            try:
                loaded = json.loads(m.group(0))
                if isinstance(loaded, dict):
                    obj = loaded
            except json.JSONDecodeError:
                return {}
    if obj is None:
        return {}
    parsed: dict[str, tuple[float, str]] = {}
    for dim in dims:
        entry = obj.get(dim.name)
        if not isinstance(entry, dict) or "score" not in entry:
            continue
        try:
            score = float(entry["score"])
        except (TypeError, ValueError):
            continue
        rationale = str(entry.get("rationale", ""))[:1000]
        parsed[dim.name] = (score, rationale)
    return parsed


# ---------------------------------------------------------------------------
# Totals + bias adjustment
# ---------------------------------------------------------------------------


def _weighted_total(scored: list[DimensionScore], dims: list[RubricDimension]) -> float:
    total_weight = sum(d.weight for d in dims) or 1.0
    # Convert each dimension to a 0..1 fraction of its max before weighting,
    # so mixing dimensions with different max_scores behaves sensibly.
    numerator = 0.0
    for score, dim in zip(scored, dims, strict=True):
        fraction = score.score / dim.max_score
        numerator += dim.weight * fraction
    return numerator / total_weight  # 0..1


def _apply_bias_adjustment(
    raw_total: float, paper: Paper, adjustment: BiasAdjustment
) -> tuple[float, list[str]]:
    notes: list[str] = []
    if not adjustment.enable_length_adjustment:
        return raw_total, notes
    word_count = _word_count(paper)
    start = adjustment.length_penalty_start
    full = adjustment.length_penalty_full
    if word_count <= start:
        return raw_total, notes
    fraction = min(1.0, (word_count - start) / (full - start))
    penalty = fraction * adjustment.max_penalty
    notes.append(
        f"Length bias: word_count={word_count}, penalty={penalty:.3f} (x of {adjustment.max_penalty:.2f})"
    )
    adjusted = max(0.0, raw_total - penalty)
    return adjusted, notes


def _word_count(paper: Paper) -> int:
    total = 0
    if paper.metadata.abstract:
        total += len(paper.metadata.abstract.split())
    for section in paper.sections:
        total += len(section.text.split())
    return total
