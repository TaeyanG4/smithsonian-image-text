#!/usr/bin/env python3
"""Phase 7 exact/near-duplicate and decoded-image QA for production outputs."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, value: int) -> int:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


@dataclass
class BKNode:
    value: int
    image_id: int
    children: dict[int, "BKNode"] = field(default_factory=dict)


class HammingBKTree:
    def __init__(self) -> None:
        self.root: BKNode | None = None

    @staticmethod
    def distance(left: int, right: int) -> int:
        return (left ^ right).bit_count()

    def add(self, value: int, image_id: int) -> None:
        if self.root is None:
            self.root = BKNode(value, image_id)
            return
        node = self.root
        while True:
            distance = self.distance(value, node.value)
            child = node.children.get(distance)
            if child is None:
                node.children[distance] = BKNode(value, image_id)
                return
            node = child

    def query(self, value: int, max_distance: int) -> list[tuple[int, int]]:
        if self.root is None:
            return []
        found: list[tuple[int, int]] = []
        stack = [self.root]
        while stack:
            node = stack.pop()
            distance = self.distance(value, node.value)
            if distance <= max_distance:
                found.append((distance, node.image_id))
            lower = distance - max_distance
            upper = distance + max_distance
            stack.extend(child for edge, child in node.children.items() if lower <= edge <= upper)
        return found


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "audits" / "production_manifest.parquet",
    )
    parser.add_argument(
        "--image-dir", type=Path, default=ROOT / "data" / "images" / "production"
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "collection.yaml")
    parser.add_argument(
        "--decisions",
        type=Path,
        default=ROOT / "data" / "audits" / "image_qa_decisions.parquet",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "data" / "audits" / "image_quality_report.json",
    )
    parser.add_argument(
        "--exact-duplicates",
        type=Path,
        default=ROOT / "data" / "audits" / "exact_duplicates.csv",
    )
    parser.add_argument(
        "--near-duplicates",
        type=Path,
        default=ROOT / "data" / "audits" / "near_duplicates.csv",
    )
    parser.add_argument(
        "--same-media",
        type=Path,
        default=ROOT / "data" / "audits" / "same_media_duplicates.csv",
    )
    parser.add_argument(
        "--near-groups",
        type=Path,
        default=ROOT / "data" / "audits" / "near_duplicate_groups.csv",
    )
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    pilot = config["pilot"]
    min_max_side = int(pilot["min_max_side_px"])
    near_threshold = int(pilot["near_duplicate_hamming_distance"])
    rows = [
        row
        for row in pq.read_table(args.manifest).to_pylist()
        if row.get("status") == "success"
    ]
    rows.sort(key=lambda row: int(row["image_id"]))

    sha_groups: dict[str, list[dict]] = defaultdict(list)
    media_groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        sha_groups[str(row.get("sha256") or "")].append(row)
        media_groups[str(row.get("media_id") or "")].append(row)

    exact_rows: list[dict] = []
    exact_drop_ids: set[int] = set()
    for digest, group in sha_groups.items():
        if not digest or len(group) <= 1:
            continue
        ordered = sorted(group, key=lambda row: int(row["image_id"]))
        keep_id = int(ordered[0]["image_id"])
        for duplicate in ordered[1:]:
            drop_id = int(duplicate["image_id"])
            exact_drop_ids.add(drop_id)
            exact_rows.append(
                {
                    "sha256": digest,
                    "keep_image_id": keep_id,
                    "drop_image_id": drop_id,
                    "keep_object_id": ordered[0].get("object_id"),
                    "drop_object_id": duplicate.get("object_id"),
                }
            )

    same_media_rows: list[dict] = []
    for media_id, group in media_groups.items():
        if not media_id or len(group) <= 1:
            continue
        same_media_rows.append(
            {
                "media_id": media_id,
                "row_count": len(group),
                "image_ids": "|".join(str(row["image_id"]) for row in group),
                "object_ids": "|".join(sorted({str(row.get("object_id") or "") for row in group})),
            }
        )

    near_rows: list[dict] = []
    tree = HammingBKTree()
    near_union = UnionFind()
    by_id = {int(row["image_id"]): row for row in rows}
    for row in rows:
        image_id = int(row["image_id"])
        phash = str(row.get("phash") or "")
        if not phash:
            continue
        value = int(phash, 16)
        for distance, other_id in tree.query(value, near_threshold):
            other = by_id[other_id]
            if row.get("sha256") == other.get("sha256"):
                continue
            near_rows.append(
                {
                    "image_id_a": other_id,
                    "image_id_b": image_id,
                    "phash_distance": distance,
                    "object_id_a": other.get("object_id"),
                    "object_id_b": row.get("object_id"),
                    "category_a": other.get("category"),
                    "category_b": row.get("category"),
                }
            )
            near_union.union(other_id, image_id)
        tree.add(value, image_id)

    component_members: dict[int, list[int]] = defaultdict(list)
    for image_id in near_union.parent:
        component_members[near_union.find(image_id)].append(image_id)
    near_group_rows: list[dict] = []
    ordered_components = sorted(
        (sorted(members) for members in component_members.values()),
        key=lambda members: (-len(members), members[0]),
    )
    for group_id, members in enumerate(ordered_components, 1):
        group_rows = [by_id[image_id] for image_id in members]
        near_group_rows.append(
            {
                "group_id": group_id,
                "image_count": len(members),
                "image_ids": "|".join(str(value) for value in members),
                "object_count": len({str(row.get("object_id") or "") for row in group_rows}),
                "object_ids": "|".join(
                    sorted({str(row.get("object_id") or "") for row in group_rows})
                ),
                "categories": "|".join(
                    sorted({str(row.get("category") or "") for row in group_rows})
                ),
                "unit_codes": "|".join(
                    sorted({str(row.get("unit_code") or "") for row in group_rows})
                ),
            }
        )

    decisions: list[dict] = []
    flag_counts: Counter[str] = Counter()
    hard_failure_counts: Counter[str] = Counter()
    for index, row in enumerate(rows, 1):
        image_id = int(row["image_id"])
        path = args.image_dir / str(row["file_name"])
        hard: list[str] = []
        flags: list[str] = []
        width = height = None
        try:
            if not path.is_file():
                raise FileNotFoundError(path)
            with Image.open(path) as image:
                image.load()
                width, height = image.size
                if image.format != "JPEG":
                    hard.append("UNEXPECTED_FINAL_FORMAT")
                if width != int(row.get("final_width") or -1) or height != int(
                    row.get("final_height") or -1
                ):
                    hard.append("DIMENSION_MISMATCH")
                if max(width, height) < min_max_side:
                    hard.append("LOW_RESOLUTION")
                aspect = width / height
                if aspect > 8 or aspect < 0.125:
                    flags.append("EXTREME_ASPECT_RATIO")
                gray = image.convert("L")
                gray.thumbnail((128, 128))
                stat = ImageStat.Stat(gray)
                if stat.stddev[0] < 2.0:
                    flags.append("LOW_VISUAL_VARIANCE")
        except Exception as exc:
            hard.append(f"DECODE_OR_FILE_ERROR:{type(exc).__name__}")

        if image_id in exact_drop_ids:
            hard.append("EXACT_DUPLICATE")
        for reason in hard:
            hard_failure_counts[reason] += 1
        for flag in flags:
            flag_counts[flag] += 1
        decisions.append(
            {
                "image_id": image_id,
                "file_name": row.get("file_name"),
                "object_id": row.get("object_id"),
                "media_id": row.get("media_id"),
                "qa_status": "exclude" if hard else "keep",
                "qa_reasons": "|".join(hard) if hard else None,
                "qa_flags": "|".join(flags) if flags else None,
                "verified_width": width,
                "verified_height": height,
            }
        )
        if index % 2500 == 0:
            print(f"qa progress {index}/{len(rows)}", flush=True)

    args.decisions.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(decisions), args.decisions, compression="zstd")
    _write_csv(
        args.exact_duplicates,
        exact_rows,
        ["sha256", "keep_image_id", "drop_image_id", "keep_object_id", "drop_object_id"],
    )
    _write_csv(
        args.near_duplicates,
        near_rows,
        [
            "image_id_a",
            "image_id_b",
            "phash_distance",
            "object_id_a",
            "object_id_b",
            "category_a",
            "category_b",
        ],
    )
    _write_csv(args.same_media, same_media_rows, ["media_id", "row_count", "image_ids", "object_ids"])
    _write_csv(
        args.near_groups,
        near_group_rows,
        [
            "group_id",
            "image_count",
            "image_ids",
            "object_count",
            "object_ids",
            "categories",
            "unit_codes",
        ],
    )

    excluded = sum(1 for row in decisions if row["qa_status"] == "exclude")
    report = {
        "production_success_rows_scanned": len(rows),
        "qa_keep_rows": len(rows) - excluded,
        "qa_exclude_rows": excluded,
        "hard_failure_counts": dict(hard_failure_counts),
        "qa_flag_counts": dict(flag_counts),
        "exact_duplicate_groups": sum(1 for group in sha_groups.values() if len(group) > 1),
        "exact_duplicate_rows_dropped": len(exact_drop_ids),
        "same_media_duplicate_groups": len(same_media_rows),
        "near_duplicate_threshold": near_threshold,
        "near_duplicate_candidate_pairs": len(near_rows),
        "near_duplicate_review_groups": len(near_group_rows),
        "largest_near_duplicate_review_group": max(
            (int(row["image_count"]) for row in near_group_rows), default=0
        ),
        "decisions": str(args.decisions),
        "exact_duplicates": str(args.exact_duplicates),
        "near_duplicates": str(args.near_duplicates),
        "near_duplicate_groups": str(args.near_groups),
        "same_media_duplicates": str(args.same_media),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
