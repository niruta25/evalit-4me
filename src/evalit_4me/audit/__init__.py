"""Fairness + disparate-impact audit module.

Runs offline over saved `EvaluationRecord`s. Exposed as `evalit audit
--input <db>` by Chunk 1.13; this module holds the computation.
"""

from evalit_4me.audit.disparate_impact import DisparateImpactResult, compute_disparate_impact
from evalit_4me.audit.fairness import FairnessReport, build_fairness_report

__all__ = [
    "DisparateImpactResult",
    "FairnessReport",
    "build_fairness_report",
    "compute_disparate_impact",
]
