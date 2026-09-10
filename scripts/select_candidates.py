#!/usr/bin/env python3
"""Build the deterministic, category-balanced Phase 4 candidate selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smithsonian_image_text.categorization import assign_category  # noqa: E402


def _rank(seed: str, row: dict) -> str:
    identity = "|".join(
        [
            str(row.get("object_id") or ""),
            str(row.get("media_id") or ""),
            str(row.get("media_url") or ""),
        ]
    )
    return hashlib.sha256(f"{seed}:{identity}".encode()).hexdigest()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "interim" / "eligible_candidates.parquet",
    )
    parser.add_argument(
        "--config", type=Path, default=ROOT / "config" / "category_mapping.yaml"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "interim" / "selected_candidates.parquet",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "data" / "audits" / "sampling_report.json",
    )
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    selection = config["selection"]
    labels = config["labels"]
    quotas = {str(key): int(value) for key, value in selection["quotas"].items()}
    order = [str(value) for value in selection["category_order"]]
    seed = str(selection["deterministic_seed"])
    max_views = int(selection["max_views_per_object"])
    max_institution = int(selection["max_rows_per_institution"])
    target = int(selection["target_rows"])

    rows = pq.read_table(args.input).to_pylist()
    categorized: dict[str, list[dict]] = {category: [] for category in quotas}
    supply_rows: Counter[str] = Counter()
    supply_objects: dict[str, set[str]] = {category: set() for category in quotas}
    for row in rows:
        category = assign_category(row, config)
        row["category"] = labels[category]
        row["category_code"] = category
        row["selection_hash"] = _rank(seed, row)
        categorized[category].append(row)
        supply_rows[category] += 1
        supply_objects[category].add(str(row.get("object_id") or ""))

    selected: list[dict] = []
    selected_per_category: Counter[str] = Counter()
    selected_per_institution: Counter[str] = Counter()
    selected_per_object: Counter[str] = Counter()
    selected_per_collection: Counter[str] = Counter()

    for category in order:
        candidates = sorted(categorized[category], key=lambda row: row["selection_hash"])
        quota = quotas[category]
        for row in candidates:
            if selected_per_category[category] >= quota:
                break
            object_id = str(row.get("object_id") or "")
            institution = str(row.get("institution") or "")
            if selected_per_object[object_id] >= max_views:
                continue
            if selected_per_institution[institution] >= max_institution:
                continue
            selected.append(row)
            selected_per_category[category] += 1
            selected_per_institution[institution] += 1
            selected_per_object[object_id] += 1
            collection = str(row.get("collection") or "")
            selected_per_collection[collection] += 1

    shortfalls = {
        category: quotas[category] - selected_per_category[category]
        for category in quotas
        if selected_per_category[category] < quotas[category]
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    if selected:
        table = pa.Table.from_pylist(selected)
        pq.write_table(table, args.output, compression="zstd")

    report = {
        "input": str(args.input),
        "target_rows": target,
        "selected_rows": len(selected),
        "selection_seed": seed,
        "max_views_per_object": max_views,
        "max_rows_per_institution": max_institution,
        "quota": quotas,
        "selected_per_category": dict(selected_per_category),
        "shortfalls": shortfalls,
        "supply_rows_per_category": dict(supply_rows),
        "supply_objects_per_category": {
            category: len(object_ids) for category, object_ids in supply_objects.items()
        },
        "selected_per_institution": dict(selected_per_institution),
        "top_collections": dict(selected_per_collection.most_common(30)),
        "selected_unique_objects": len(selected_per_object),
        "max_selected_views_for_one_object": max(selected_per_object.values(), default=0),
        "output": str(args.output),
        "image_bytes_read": 0,
    }
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if len(selected) == target and not shortfalls else 2


if __name__ == "__main__":
    raise SystemExit(main())
