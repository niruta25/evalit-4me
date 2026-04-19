"""JSON dump helpers.

Pydantic gives us serialization for free; this module is just the canonical
entry point so callers don't have to think about indentation and default
datetime handling.
"""

from __future__ import annotations

from evalit_4me.contracts import EvaluationRecord, ReviewDraft


def dump_record_json(record: EvaluationRecord, *, indent: int | None = 2) -> str:
    return record.model_dump_json(indent=indent)


def dump_review_json(draft: ReviewDraft, *, indent: int | None = 2) -> str:
    return draft.model_dump_json(indent=indent)
