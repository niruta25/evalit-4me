"""Stage 3 — Depth analyzer.

Scores four dimensions in [0, 1] each:

    methodology_score       — is the methodology section well-specified?
    limitations_score       — is there a limitations / broader-impact discussion?
    reproducibility_score   — are code/data/hyperparameters / seeds mentioned?
    logical_soundness_score — do intro claims connect to results? (coarse)

Heuristics are deliberately deterministic; the plan explicitly allows
dropping logical-fallacy LLM detection for v0.1. A provider argument is
reserved for future upgrades but not used yet — keeping this stage free
of per-run LLM cost matches the goal of budget-friendly Phase 2 benchmarks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from evalit_4me.contracts import DepthReport, Paper, Section
from evalit_4me.llm.protocol import LLMProvider

_METHODOLOGY_TITLES = {"method", "methods", "methodology", "approach", "model", "architecture"}
_LIMITATIONS_TITLES = {
    "limitations",
    "limitation",
    "broader impact",
    "broader impacts",
    "discussion",
    "ethics",
}
_RESULTS_TITLES = {"results", "experiments", "experiment", "evaluation", "analysis"}
_INTRO_TITLES = {"introduction", "background"}
_CONCLUSION_TITLES = {"conclusion", "conclusions", "future work"}

_DATASET_CUES = re.compile(
    r"\b(?:dataset|benchmark|corpus|MNIST|CIFAR|ImageNet|GLUE|SuperGLUE|"
    r"WMT|SQuAD|COCO|LibriSpeech|OpenReview|arXiv)\b",
    re.IGNORECASE,
)
_BASELINE_CUES = re.compile(
    r"\b(?:baseline|baselines|comparison|compared\s+to|vs\.?)\b", re.IGNORECASE
)
_ABLATION_CUES = re.compile(r"\babla(?:tion|te|ted)\b", re.IGNORECASE)
_METRIC_CUES = re.compile(
    r"\b(?:accuracy|precision|recall|F1|BLEU|ROUGE|AUC|mAP|perplexity|error\s+rate)\b",
    re.IGNORECASE,
)
_CODE_URL_RE = re.compile(
    r"https?://(?:github\.com|gitlab\.com|huggingface\.co|zenodo\.org|codeocean\.com)/\S+"
)
_SEED_CUES = re.compile(
    r"\b(?:random\s+seed|np\.random|torch\.manual_seed|seed\s*=\s*\d+)\b", re.IGNORECASE
)
_HYPERPARAM_CUES = re.compile(
    r"\b(?:learning\s+rate|batch\s+size|hyperparameter|optimizer|Adam|SGD|"
    r"dropout|weight\s+decay|epoch|warmup)\b",
    re.IGNORECASE,
)
_LIMITATION_WORDS = re.compile(
    r"\b(?:limitation|shortcoming|caveat|weakness|does\s+not\s+generalize|"
    r"fails\s+to|cannot|future\s+work|broader\s+impact)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DepthConfig:
    """Thresholds for each dimension. Tweakable for custom venues."""

    reproducibility_cues_per_section_cap: int = 5


def analyze_depth(
    paper: Paper,
    provider: LLMProvider | None = None,
    *,
    config: DepthConfig | None = None,
) -> DepthReport:
    cfg = config or DepthConfig()
    # `provider` is unused in v0.1. Accepting it keeps the orchestrator
    # signature stable when we upgrade to LLM-augmented scoring.
    _ = provider

    methodology_score, methodology_rat = _score_methodology(paper)
    limitations_score, limitations_rat = _score_limitations(paper)
    reproducibility_score, reproducibility_rat = _score_reproducibility(paper, cfg)
    logical_score, logical_rat = _score_logical_soundness(paper)

    return DepthReport(
        methodology_score=round(methodology_score, 4),
        limitations_score=round(limitations_score, 4),
        reproducibility_score=round(reproducibility_score, 4),
        logical_soundness_score=round(logical_score, 4),
        rationales={
            "methodology": methodology_rat,
            "limitations": limitations_rat,
            "reproducibility": reproducibility_rat,
            "logical_soundness": logical_rat,
        },
    )


# ---------------------------------------------------------------------------
# Per-dimension scoring
# ---------------------------------------------------------------------------


def _score_methodology(paper: Paper) -> tuple[float, str]:
    sections = _sections_by_category(paper)
    method_text = " ".join(s.text for s in sections["method"])
    if not method_text:
        return 0.0, "No methodology section found."
    signals: list[tuple[str, bool]] = [
        ("dataset_mentioned", bool(_DATASET_CUES.search(method_text))),
        ("baseline_mentioned", bool(_BASELINE_CUES.search(method_text))),
        ("ablation_discussed", bool(_ABLATION_CUES.search(method_text))),
        ("metric_named", bool(_METRIC_CUES.search(method_text))),
        ("substantive_length", len(method_text.split()) >= 150),
    ]
    score = sum(1 for _, hit in signals if hit) / len(signals)
    hits = [name for name, hit in signals if hit]
    return score, f"Methodology signals present: {', '.join(hits) or 'none'}"


def _score_limitations(paper: Paper) -> tuple[float, str]:
    sections = _sections_by_category(paper)
    explicit = sections["limitations"]
    if explicit:
        body = " ".join(s.text for s in explicit)
        words = len(body.split())
        # 50 words ≈ terse, 200+ substantive.
        score = min(1.0, words / 200.0)
        # Gate: dedicated section gets at least 0.5.
        score = max(score, 0.5)
        return score, f"Dedicated limitations/discussion section ({words} words)"
    # Scan conclusion + discussion for limitation-flavored language.
    fallback_text = " ".join(
        s.text
        for s in paper.sections
        if _canonical_title(s) in _CONCLUSION_TITLES | _LIMITATIONS_TITLES
    )
    hits = len(_LIMITATION_WORDS.findall(fallback_text))
    if hits == 0:
        return 0.0, "No limitations section and no limitation-flavored language."
    score = min(0.5, hits * 0.1)
    return score, f"Limitations language mentioned {hits} time(s) in conclusion-adjacent sections."


def _score_reproducibility(paper: Paper, config: DepthConfig) -> tuple[float, str]:
    full_text = " ".join(s.text for s in paper.sections)
    signals: dict[str, bool] = {
        "code_url": bool(_CODE_URL_RE.search(full_text)),
        "seed_mentioned": bool(_SEED_CUES.search(full_text)),
        "hyperparameters": bool(_HYPERPARAM_CUES.search(full_text)),
        "dataset_named": bool(_DATASET_CUES.search(full_text)),
    }
    hit_names = [k for k, v in signals.items() if v]
    score = len(hit_names) / len(signals)
    return score, f"Reproducibility cues: {', '.join(hit_names) or 'none'}"


def _score_logical_soundness(paper: Paper) -> tuple[float, str]:
    """Very coarse structural sanity check: does the paper have the
    expected intro -> method -> results -> conclusion skeleton, and do
    results get mentioned in the conclusion?"""
    sections = _sections_by_category(paper)
    skeleton_parts = [
        ("introduction", bool(sections["intro"])),
        ("method", bool(sections["method"])),
        ("results", bool(sections["results"])),
        ("conclusion", bool(sections["conclusion"])),
    ]
    score = sum(1 for _, present in skeleton_parts if present) / len(skeleton_parts)

    # Bonus: conclusion references the results section (shared keyword).
    conclusion_text = " ".join(s.text for s in sections["conclusion"]).lower()
    results_text = " ".join(s.text for s in sections["results"]).lower()
    if conclusion_text and results_text:
        result_keywords = set(re.findall(r"[a-z]{5,}", results_text[:2000]))
        conclusion_keywords = set(re.findall(r"[a-z]{5,}", conclusion_text[:2000]))
        shared = result_keywords & conclusion_keywords
        if len(shared) >= 5:
            score = min(1.0, score + 0.1)

    missing = [name for name, present in skeleton_parts if not present]
    rationale = (
        "All skeleton parts present."
        if not missing
        else f"Missing skeleton parts: {', '.join(missing)}"
    )
    return score, rationale


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_title(section: Section) -> str:
    return section.title.strip().lower()


def _sections_by_category(paper: Paper) -> dict[str, list[Section]]:
    out: dict[str, list[Section]] = {
        "intro": [],
        "method": [],
        "results": [],
        "conclusion": [],
        "limitations": [],
    }
    for s in paper.sections:
        title = _canonical_title(s)
        if any(t in title for t in _INTRO_TITLES):
            out["intro"].append(s)
        if any(t in title for t in _METHODOLOGY_TITLES):
            out["method"].append(s)
        if any(t in title for t in _RESULTS_TITLES):
            out["results"].append(s)
        if any(t in title for t in _CONCLUSION_TITLES):
            out["conclusion"].append(s)
        if any(t in title for t in _LIMITATIONS_TITLES):
            out["limitations"].append(s)
    return out
