#!/usr/bin/env python3
"""Add deterministic leakage-safe object-level train/validation/test splits."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smithsonian_image_text.splitting import assign_object_splits  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "interim" / "metadata_pre_split.parquet",
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "collection.yaml")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "interim" / "metadata_final.parquet",
    )
    parser.add_argument(
        "--report", type=Path, default=ROOT / "data" / "audits" / "split_report.json"
    )
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    split_config = config["splitting"]
    ratios = {
        "train": float(split_config["train"]),
        "validation": float(split_config["validation"]),
        "test": float(split_config["test"]),
    }
    rows = pq.read_table(args.input).to_pylist()
    assignments = assign_object_splits(rows, seed=str(split_config["seed"]), ratios=ratios)
    for row in rows:
        row["split"] = assignments[str(row["object_id"])]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), args.output, compression="zstd")

    objects_by_split: dict[str, set[str]] = defaultdict(set)
    split_rows = Counter()
    category_by_split: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        split = str(row["split"])
        object_id = str(row["object_id"])
        objects_by_split[split].add(object_id)
        split_rows[split] += 1
        category_by_split[split][str(row.get("category_code"))] += 1
    intersections = {
        "train_validation": len(objects_by_split["train"] & objects_by_split["validation"]),
        "train_test": len(objects_by_split["train"] & objects_by_split["test"]),
        "validation_test": len(objects_by_split["validation"] & objects_by_split["test"]),
    }
    if any(intersections.values()):
        raise RuntimeError(f"Object leakage detected: {intersections}")

    report = {
        "rows": len(rows),
        "objects": len(assignments),
        "seed": split_config["seed"],
        "target_ratios": ratios,
        "rows_by_split": dict(split_rows),
        "objects_by_split": {split: len(values) for split, values in objects_by_split.items()},
        "category_rows_by_split": {
            split: dict(counts) for split, counts in category_by_split.items()
        },
        "object_leakage_intersections": intersections,
        "output": str(args.output),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
