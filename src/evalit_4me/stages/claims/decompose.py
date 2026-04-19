"""LLM-driven atomic claim decomposition.

Design notes:

* One LLM call per section. Cheap Sonnet-tier is sufficient; prompt is
  temperature=0 + seed=0 for reproducibility.
* The LLM returns only `text` and `ref_ids` per claim. Categorization and
  severity are deterministic (see `categorize.py`, `severity.py`) so the
  cost-sensitive LLM step stays narrow.
* Source spans are recovered by searching the section text for the claim
  text. When no substring match is found, we fall back to the full section
  span — good enough for traceability, and it prevents the whole pipeline
  from failing on a paraphrase.
* Malformed LLM output is tolerated: we attempt a strict JSON parse, then
  an array-find fallback, then return []. A malformed section never stops
  the paper from being processed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from evalit_4me.contracts import Claim, Section, SourceSpan
from evalit_4me.llm.protocol import LLMProvider, LLMRequest
from evalit_4me.stages.claims.categorize import categorize
from evalit_4me.stages.claims.prompts import render_decompose_prompt
from evalit_4me.stages.claims.severity import assign_severity

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_CLAIMS_PER_SECTION = 10
DEFAULT_MAX_TOKENS = 1024


# Section titles that are noise for claim extraction. Abstract is covered
# by the body sections; references/acknowledgements carry no claims.
_SKIP_SECTION_RE = re.compile(
    r"^\s*(?:references|bibliography|acknowledg(?:e?ments?|ments)|"
    r"appendix(?:\s+[A-Z])?|author\s+contributions|funding)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DecomposeConfig:
    model: str = DEFAULT_MODEL
    max_claims_per_section: int = DEFAULT_MAX_CLAIMS_PER_SECTION
    max_tokens: int = DEFAULT_MAX_TOKENS
    seed: int = 0


class _RawClaim(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str = Field(min_length=1)
    ref_ids: list[str] = Field(default_factory=list)


def decompose_claims(
    paper,  # Paper — forward-ref to avoid circular import
    provider: LLMProvider,
    *,
    config: DecomposeConfig | None = None,
) -> list[Claim]:
    """Extract atomic claims from every content-bearing section of `paper`."""
    cfg = config or DecomposeConfig()
    known_ref_ids = [r.id for r in paper.references]

    claims: list[Claim] = []
    counter = 1
    for section in paper.sections:
        if _should_skip(section):
            continue
        raw_list = _extract_raw_from_section(
            section=section,
            provider=provider,
            config=cfg,
            known_ref_ids=known_ref_ids,
        )
        for raw in raw_list:
            ref_ids = _filter_ref_ids(raw.ref_ids, known_ref_ids)
            span = _locate_span(section=section, claim_text=raw.text)
            partial = Claim(
                id=f"claim-{counter}",
                text=raw.text.strip(),
                claim_type=categorize(raw.text, has_citation_refs=bool(ref_ids)),
                severity=_PLACEHOLDER_SEVERITY,
                source_span=span,
                referenced_citation_ids=ref_ids,
            )
            final = partial.model_copy(update={"severity": assign_severity(partial)})
            claims.append(final)
            counter += 1
    return claims


def build_claims(
    paper,  # Paper — forward-ref
    provider: LLMProvider,
    *,
    config: DecomposeConfig | None = None,
) -> list[Claim]:
    """Alias for `decompose_claims`. Kept as a separate public name so that
    future refinements (e.g. cross-section deduplication) can plug in here
    without touching the decomposition primitive."""
    return decompose_claims(paper, provider, config=config)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

# Severity validator requires a real enum value; we overwrite immediately
# after categorizing, but need a placeholder that matches the contract.
from evalit_4me.contracts import Severity  # noqa: E402

_PLACEHOLDER_SEVERITY = Severity.LOW


def _should_skip(section: Section) -> bool:
    if not section.text.strip():
        return True
    return bool(_SKIP_SECTION_RE.match(section.title))


def _extract_raw_from_section(
    *,
    section: Section,
    provider: LLMProvider,
    config: DecomposeConfig,
    known_ref_ids: list[str],
) -> list[_RawClaim]:
    system, user = render_decompose_prompt(
        section_title=section.title,
        section_text=section.text,
        ref_ids=known_ref_ids,
        max_claims=config.max_claims_per_section,
    )
    request = LLMRequest(
        prompt=user,
        system=system,
        model=config.model,
        temperature=0.0,
        max_tokens=config.max_tokens,
        seed=config.seed,
    )
    response = provider.complete(request)
    return parse_decompose_response(response.text, limit=config.max_claims_per_section)


def parse_decompose_response(raw: str, *, limit: int) -> list[_RawClaim]:
    """Parse an LLM response into `_RawClaim`s, tolerant of common failures.

    Accepts:
    - Pure JSON array: `[{"text": ..., "ref_ids": [...]}, ...]`
    - JSON fenced in ```json ... ```
    - JSON array embedded anywhere in the text (we extract the first one)

    Returns at most `limit` entries. Unparseable input yields [].
    """
    candidate = _strip_fences(raw).strip()
    if not candidate:
        return []

    parsed = _try_json_array(candidate)
    if parsed is None:
        parsed = _extract_embedded_array(candidate)
    if parsed is None:
        return []

    out: list[_RawClaim] = []
    for item in parsed[:limit]:
        if not isinstance(item, dict):
            continue
        try:
            out.append(_RawClaim.model_validate(item))
        except ValidationError:
            continue
    return out


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text)


def _try_json_array(text: str) -> list | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _extract_embedded_array(text: str) -> list | None:
    m = _ARRAY_RE.search(text)
    if not m:
        return None
    return _try_json_array(m.group(0))


def _filter_ref_ids(candidate: list[str], known: list[str]) -> list[str]:
    """Drop ref_ids the LLM hallucinated into existence."""
    known_set = set(known)
    return [r for r in candidate if r in known_set]


def _locate_span(*, section: Section, claim_text: str) -> SourceSpan:
    """Find the claim inside the section text; fall back to whole section.

    Matching is case-insensitive and whitespace-tolerant. We search for the
    longest prefix of the claim (down to 40 chars) to accommodate the common
    case where the LLM rephrased the original sentence.
    """
    text = section.text
    if not text:
        return SourceSpan(section_id=section.id, char_start=0, char_end=0)

    lowered = text.lower()
    needle = claim_text.lower().strip()
    min_len = 40
    for length in (len(needle), max(min_len, len(needle) // 2), min_len):
        if length <= 0 or length > len(needle):
            continue
        fragment = needle[:length]
        idx = lowered.find(fragment)
        if idx != -1:
            return SourceSpan(
                section_id=section.id,
                char_start=idx,
                char_end=min(idx + length, len(text)),
            )
    return SourceSpan(section_id=section.id, char_start=0, char_end=len(text))
