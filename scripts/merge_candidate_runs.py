#!/usr/bin/env python3
"""Merge metadata-only discovery runs while removing exact candidate-row overlap."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[str, str, str]] = set()
    per_input: dict[str, int] = {}
    written = 0
    duplicates_skipped = 0

    with gzip.open(args.output, "wt", encoding="utf-8", newline="\n") as destination:
        for path in args.inputs:
            count = 0
            with _open_text(path) as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    key = (
                        str(row.get("object_id") or ""),
                        str(row.get("media_id") or ""),
                        str(row.get("media_url") or ""),
                    )
                    if key in seen:
                        duplicates_skipped += 1
                        continue
                    seen.add(key)
                    destination.write(
                        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                    )
                    count += 1
                    written += 1
            per_input[str(path)] = count

    report = {
        "mode": "metadata_only",
        "image_bytes_read": 0,
        "inputs": [str(path) for path in args.inputs],
        "per_input_rows_written": per_input,
        "rows_written": written,
        "exact_candidate_overlap_skipped": duplicates_skipped,
        "output": str(args.output),
    }
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
