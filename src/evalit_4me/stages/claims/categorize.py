"""Deterministic claim categorization.

We deliberately do NOT use the LLM for this stage — categorization signals
(keyword patterns, citation presence, numeric tokens) are cheap and stable
enough that regex rules beat an LLM on cost and determinism. The LLM already
did the hard part during decomposition.

Rule priority (first match wins):
    CITATION    — claim references one or more paper references
    STATISTICAL — claim contains numeric results (percentages, p-values, F1/BLEU/AUC)
    TEMPORAL    — claim contains year, "since/before/after YEAR" patterns
    CAPABILITY  — claim uses capability phrasing ("can", "able to", "enables")
    EMPIRICAL   — fallback (empirical observation without explicit stats)
"""

from __future__ import annotations

import re

from evalit_4me.contracts import ClaimType

STAT_NUMERIC_RE = re.compile(
    r"""
    \b(?:
        \d+(?:\.\d+)?\s*%           |   # 12%, 94.5%
        [Pp]\s*[<>=]\s*0\.\d+       |   # p<0.05
        (?:F1|BLEU|ROUGE|AUC|mAP|Top-?\d|AP|PR-AUC|R\^2|R-squared)
            \s*(?:score)?\s*[:=]?\s*\d+(?:\.\d+)?  |
        \d+(?:\.\d+)?\s*(?:times|fold|x)\s+(?:better|faster|higher|lower)
    )
    """,
    re.VERBOSE,
)

# Plain numeric mentions we treat as statistical only if they look like
# measurements (>= 2 digits OR has a decimal).
STAT_FALLBACK_RE = re.compile(r"\b\d+\.\d+\b|\b\d{2,}\b")

TEMPORAL_RE = re.compile(
    r"\b(?:since|before|after|prior\s+to|as\s+of)\s+(?:19|20)\d{2}\b"
    r"|\b(?:19|20)\d{2}\b",
    re.IGNORECASE,
)

CAPABILITY_RE = re.compile(
    r"\b(?:can|could|able\s+to|capable\s+of|enables?|allows?|achieves?\s+to)\b",
    re.IGNORECASE,
)


def categorize(text: str, *, has_citation_refs: bool) -> ClaimType:
    """Return the single best-fit `ClaimType` for the given claim."""
    # 1. Citation: explicit reference id OR inline [Author, Year]-style marker.
    if has_citation_refs or _looks_like_inline_citation(text):
        return ClaimType.CITATION

    # 2. Statistical: strong numeric patterns first, then weak fallback.
    if STAT_NUMERIC_RE.search(text):
        return ClaimType.STATISTICAL
    if STAT_FALLBACK_RE.search(text) and _looks_quantitative(text):
        return ClaimType.STATISTICAL

    # 3. Temporal.
    if TEMPORAL_RE.search(text):
        return ClaimType.TEMPORAL

    # 4. Capability.
    if CAPABILITY_RE.search(text):
        return ClaimType.CAPABILITY

    # 5. Default: empirical observation.
    return ClaimType.EMPIRICAL


_INLINE_CITATION_RE = re.compile(
    # [Author et al., YYYY] or (Author et al., YYYY)
    r"\[[A-Z][A-Za-z]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z]+))?,\s*(?:19|20)\d{2}\]"
    r"|\([A-Z][A-Za-z]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z]+))?,\s*(?:19|20)\d{2}\)"
    # Author et al. (YYYY) — year alone in parens, name outside.
    r"|\b[A-Z][A-Za-z]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z]+))?\s*\(\s*(?:19|20)\d{2}[a-z]?\s*\)"
    # Bare [N] citation marker.
    r"|\[\d+\]"
)


def _looks_like_inline_citation(text: str) -> bool:
    return _INLINE_CITATION_RE.search(text) is not None


_QUANT_CUE_RE = re.compile(
    r"\b(?:accuracy|precision|recall|score|loss|error|improve|gain|reduce|"
    r"increase|decrease|outperform|compared|average|mean|median|std)\b",
    re.IGNORECASE,
)


def _looks_quantitative(text: str) -> bool:
    """Supporting cue for the STAT_FALLBACK branch — avoids classifying
    'in 1024 tokens' or '10 layers' as statistical results."""
    return _QUANT_CUE_RE.search(text) is not None
