"""Stage 2a — claim decomposition, categorization, severity.

Public surface:

* `decompose_claims(paper, provider, *, model)`      -> list[Claim]
* `categorize(text, has_citation_refs)`              -> ClaimType
* `assign_severity(claim)`                           -> Severity
* `build_claims(paper, provider, *, model)`          -> list[Claim]  (full pipeline)

Downstream verification (Stage 2b/2c) consumes the `list[Claim]`; ledger
aggregation happens in `stages.verify.confidence`.
"""

from evalit_4me.stages.claims.categorize import categorize
from evalit_4me.stages.claims.decompose import build_claims, decompose_claims
from evalit_4me.stages.claims.severity import assign_severity

__all__ = [
    "assign_severity",
    "build_claims",
    "categorize",
    "decompose_claims",
]
