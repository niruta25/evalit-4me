#!/usr/bin/env python3
"""Recompute the composite score for a saved record with custom weights.

usage:  recompute_composite.py <record.json> weight=value [...]

Weight keys: compliance, verification, depth, rubric
Missing keys inherit the default (0.15 / 0.20 / 0.20 / 0.45).

Prints a JSON object with the before/after composite + new recommendation.
"""

from __future__ import annotations

import sys


def _parse_weights(tokens: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for tok in tokens:
        if "=" not in tok:
            raise SystemExit(f"bad weight spec: {tok!r} (expected key=value)")
        k, v = tok.split("=", 1)
        out[k.strip()] = float(v)
    return out


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: recompute_composite.py <record.json> weight=value [...]",
            file=sys.stderr,
        )
        return 2
    record_path = sys.argv[1]
    weights = _parse_weights(sys.argv[2:])

    from evalit_4me.skill_helpers import recompute_composite, recompute_to_json

    result = recompute_composite(record_path, weights)
    print(recompute_to_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
