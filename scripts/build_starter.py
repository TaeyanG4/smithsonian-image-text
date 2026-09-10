#!/usr/bin/env python3
"""Build the deterministic category-balanced 5K starter subset from final metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _allocate(weights: dict[str, int], target: int) -> dict[str, int]:
    total = sum(weights.values())
    exact = {key: target * value / total for key, value in weights.items()}
    result = {key: math.floor(value) for key, value in exact.items()}
    remaining = target - sum(result.values())
    order = sorted(weights, key=lambda key: (-(exact[key] - result[key]), key))
    for key in order[:remaining]:
        result[key] += 1
    return result


def _rank(seed: str, row: dict) -> str:
    identity = f"{row.get('object_id')}|{row.get('media_id')}|{row.get('sha256')}"
    return hashlib.sha256(f"{seed}:{identity}".encode()).hexdigest()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "interim" / "metadata_final.parquet",
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "collection.yaml")
    parser.add_argument(
        "--category-config", type=Path, default=ROOT / "config" / "category_mapping.yaml"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "interim" / "starter_5k.parquet",
    )
    parser.add_argument(
        "--report", type=Path, default=ROOT / "data" / "audits" / "starter_report.json"
    )
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    category_config = yaml.safe_load(args.category_config.read_text(encoding="utf-8"))
    target = int(config["project"]["starter_images"])
    seed = str(config["starter"]["seed"])
    max_views = int(config["starter"]["max_views_per_object"])
    weights = {
        str(key): int(value) for key, value in category_config["selection"]["quotas"].items()
    }
    requested = _allocate(weights, target)
    rows = pq.read_table(args.input).to_pylist()
    grouped: dict[str, list[dict]] = {category: [] for category in requested}
    for row in rows:
        category = str(row.get("category_code") or "")
        if category in grouped:
            row["starter_hash"] = _rank(seed, row)
            grouped[category].append(row)

    selected: list[dict] = []
    selected_per_object: Counter[str] = Counter()
    selected_per_category: Counter[str] = Counter()
    for category, count in requested.items():
        for row in sorted(grouped[category], key=lambda value: value["starter_hash"]):
            if selected_per_category[category] >= count:
                break
            object_id = str(row.get("object_id") or "")
            if selected_per_object[object_id] >= max_views:
                continue
            selected.append(row)
            selected_per_object[object_id] += 1
            selected_per_category[category] += 1

    if len(selected) != target:
        raise RuntimeError(
            f"Starter selection underfilled: selected={len(selected)} target={target}"
        )
    selected.sort(key=lambda row: int(row["image_id"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(selected), args.output, compression="zstd")

    split_counts = Counter(str(row.get("split")) for row in selected)
    institution_counts = Counter(str(row.get("institution")) for row in selected)
    objects_by_split: dict[str, set[str]] = {
        split: {str(row["object_id"]) for row in selected if row.get("split") == split}
        for split in ("train", "validation", "test")
    }
    leakage = {
        "train_validation": len(objects_by_split["train"] & objects_by_split["validation"]),
        "train_test": len(objects_by_split["train"] & objects_by_split["test"]),
        "validation_test": len(objects_by_split["validation"] & objects_by_split["test"]),
    }
    report = {
        "target_rows": target,
        "selected_rows": len(selected),
        "requested_per_category": requested,
        "selected_per_category": dict(selected_per_category),
        "unique_objects": len(selected_per_object),
        "max_views_per_object": max(selected_per_object.values(), default=0),
        "rows_by_split": dict(split_counts),
        "object_leakage_intersections": leakage,
        "institution_distribution": dict(institution_counts),
        "output": str(args.output),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
