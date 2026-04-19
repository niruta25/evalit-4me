"""Prompt templates for claim decomposition.

Kept in a dedicated module so Chunk 1.7 (entailment) and Chunk 1.9 (rubric)
can share the JSON-extraction helper without cross-importing.
"""

from __future__ import annotations

DECOMPOSE_SYSTEM = """You are a rigorous scientific-paper auditor.
Your job is to extract ATOMIC, VERIFIABLE claims from a section of a paper.
A claim is atomic if it states exactly one fact. It is verifiable if a
reviewer could in principle check it against evidence (a cited source, a
statistical result, a capability demonstration, or a temporal assertion).

Output rules:
- Return ONLY a JSON array. No prose, no fences, no trailing commentary.
- Each element is an object with these keys:
    "text"    : the claim, rewritten as a single sentence
    "ref_ids" : list of reference ids mentioned in the claim (may be [])
- Return at most {max_claims} claims. Prefer the most load-bearing ones.
- If the section contains no verifiable claims, return [].
"""

DECOMPOSE_USER = """Section title: {section_title}

Reference ids available in this paper: {ref_ids}

Section text:
---
{section_text}
---

Return the JSON array now."""


def render_decompose_prompt(
    *,
    section_title: str,
    section_text: str,
    ref_ids: list[str],
    max_claims: int,
) -> tuple[str, str]:
    system = DECOMPOSE_SYSTEM.format(max_claims=max_claims)
    user = DECOMPOSE_USER.format(
        section_title=section_title,
        section_text=section_text,
        ref_ids=", ".join(ref_ids) if ref_ids else "(none)",
    )
    return system, user
