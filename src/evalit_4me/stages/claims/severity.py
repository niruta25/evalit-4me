"""Deterministic severity assignment.

Severity encodes *how bad it would be if this claim turned out to be wrong*,
not the LLM's confidence. A wrong-but-minor claim (an uncited date) is LOW;
a wrong-but-load-bearing claim (a fake SOTA number tied to a citation) is
CRITICAL.

Base severity by claim type:
    CITATION     HIGH      (unverified cite is a fabrication risk)
    STATISTICAL  HIGH      (numbers drive conclusions)
    CAPABILITY   MEDIUM    (prone to overclaim)
    EMPIRICAL    MEDIUM    (usually hedgeable)
    TEMPORAL     LOW       (rarely load-bearing on its own)

Escalation to CRITICAL when the claim text contains at least one
superlative/novelty marker AND the base is HIGH — matches the paper's
"verify load-bearing claims first" policy.
"""

from __future__ import annotations

import re

from evalit_4me.contracts import Claim, ClaimType, Severity

_BASE: dict[ClaimType, Severity] = {
    ClaimType.CITATION: Severity.HIGH,
    ClaimType.STATISTICAL: Severity.HIGH,
    ClaimType.CAPABILITY: Severity.MEDIUM,
    ClaimType.EMPIRICAL: Severity.MEDIUM,
    ClaimType.TEMPORAL: Severity.LOW,
}

_CRITICAL_MARKERS_RE = re.compile(
    r"\b(?:state[-\s]of[-\s]the[-\s]art|SOTA|first\s+to|"
    r"outperforms?\s+(?:all|every|prior|existing|the\s+best)|"
    r"novel(?:ly)?|breakthrough|proves?|guarantees?|"
    r"best(?:\s+ever)?\s+reported|unprecedented)\b",
    re.IGNORECASE,
)


def assign_severity(claim: Claim) -> Severity:
    """Map a `Claim` to a `Severity` using its type and load-bearing signals."""
    base = _BASE.get(claim.claim_type, Severity.MEDIUM)
    if base is Severity.HIGH and _CRITICAL_MARKERS_RE.search(claim.text):
        return Severity.CRITICAL
    return base
