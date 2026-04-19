#!/usr/bin/env python3
"""Produce a side-by-side markdown comparison of N saved records.

usage:  compare_records.py <record1.json> [<record2.json> ...]

Prints the comparison markdown to stdout.
"""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: compare_records.py <record1.json> [<record2.json> ...]", file=sys.stderr)
        return 2
    from evalit_4me.skill_helpers import compare_records

    print(compare_records(sys.argv[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
