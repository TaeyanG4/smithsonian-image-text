#!/usr/bin/env python3
"""Phase 13 final release QA for the local Kaggle package."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _data_line_count(path: Path) -> int:
    if not path.is_file():
        return -1
    with path.open("r", encoding="utf-8-sig") as stream:
        return sum(1 for line in stream if line.strip())


def _verify_checksums(release_dir: Path, checksum_path: Path) -> tuple[int, list[str]]:
    failures: list[str] = []
    checked = 0
    if not checksum_path.is_file():
        return checked, ["checksums.sha256 missing"]
    with checksum_path.open("r", encoding="ascii") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                expected, relative = line.rstrip("\n").split("  ", 1)
            except ValueError:
                failures.append(f"invalid checksum line {line_number}")
                continue
            path = release_dir / Path(relative)
            if not path.is_file():
                failures.append(f"missing checksum target: {relative}")
                continue
            actual = _sha256(path)
            checked += 1
            if actual != expected:
                failures.append(f"checksum mismatch: {relative}")
    return checked, failures


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-dir", type=Path, default=ROOT / "data" / "release" / "museum-images"
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "collection.yaml")
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "data" / "audits" / "release_validation_report.json",
    )
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    project = config["project"]
    metadata_path = args.release_dir / "metadata.parquet"
    rows = pq.read_table(metadata_path).to_pylist()
    starter_rows = pq.read_table(args.release_dir / "starter_5k" / "metadata.parquet").to_pylist()
    errors: list[str] = []

    image_ids = [int(row["image_id"]) for row in rows]
    file_names = [str(row["file_name"]) for row in rows]
    if len(image_ids) != len(set(image_ids)):
        errors.append("DUPLICATE_IMAGE_ID")
    if len(file_names) != len(set(file_names)):
        errors.append("DUPLICATE_FILE_NAME")
    if not int(project["min_final_images"]) <= len(rows) <= int(project["target_final_images"]):
        errors.append("FINAL_IMAGE_COUNT_OUT_OF_RANGE")
    if len(starter_rows) != int(project["starter_images"]):
        errors.append("STARTER_COUNT_MISMATCH")

    missing_source = sum(not row.get("source_url") for row in rows)
    missing_object = sum(not row.get("object_id") for row in rows)
    bad_rights = sum(
        row.get("rights") != "CC0"
        or row.get("metadata_rights") != "CC0"
        or row.get("media_rights") != "CC0"
        for row in rows
    )
    missing_text = sum(not str(row.get("model_text") or "").strip() for row in rows)
    if missing_source:
        errors.append("MISSING_SOURCE_URL")
    if missing_object:
        errors.append("MISSING_OBJECT_ID")
    if bad_rights:
        errors.append("NON_CC0_RIGHTS")

    usable_text_ratio = 1 - missing_text / len(rows) if rows else 0.0
    if usable_text_ratio < 0.90:
        errors.append("TEXT_USABLE_RATIO_BELOW_90_PERCENT")

    objects_by_split: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        objects_by_split[str(row["split"])].add(str(row["object_id"]))
    leakage = {
        "train_validation": len(objects_by_split["train"] & objects_by_split["validation"]),
        "train_test": len(objects_by_split["train"] & objects_by_split["test"]),
        "validation_test": len(objects_by_split["validation"] & objects_by_split["test"]),
    }
    if any(leakage.values()):
        errors.append("OBJECT_SPLIT_LEAKAGE")

    full_identity = {
        (int(row["image_id"]), str(row["object_id"]), str(row["file_name"])) for row in rows
    }
    starter_identity = {
        (int(row["image_id"]), str(row["object_id"]), str(row["file_name"]))
        for row in starter_rows
    }
    starter_not_subset = starter_identity - full_identity
    if starter_not_subset:
        errors.append("STARTER_NOT_SUBSET_OF_FULL_METADATA")
    starter_objects_by_split: dict[str, set[str]] = defaultdict(set)
    for row in starter_rows:
        starter_objects_by_split[str(row["split"])].add(str(row["object_id"]))
    starter_leakage = {
        "train_validation": len(
            starter_objects_by_split["train"] & starter_objects_by_split["validation"]
        ),
        "train_test": len(starter_objects_by_split["train"] & starter_objects_by_split["test"]),
        "validation_test": len(
            starter_objects_by_split["validation"] & starter_objects_by_split["test"]
        ),
    }
    if any(starter_leakage.values()):
        errors.append("STARTER_OBJECT_SPLIT_LEAKAGE")

    missing_images = 0
    decode_failures = 0
    dimension_mismatches = 0
    total_image_bytes = 0
    image_dir = args.release_dir / "images"
    for index, row in enumerate(rows, 1):
        path = image_dir / str(row["file_name"])
        if not path.is_file():
            missing_images += 1
            continue
        total_image_bytes += path.stat().st_size
        try:
            with Image.open(path) as image:
                image.load()
                if image.size != (int(row["width"]), int(row["height"])):
                    dimension_mismatches += 1
        except Exception:
            decode_failures += 1
        if index % 5000 == 0:
            print(f"release validation {index}/{len(rows)}", flush=True)
    if missing_images:
        errors.append("MISSING_IMAGE_FILES")
    if decode_failures:
        errors.append("IMAGE_DECODE_FAILURE")
    if dimension_mismatches:
        errors.append("IMAGE_DIMENSION_MISMATCH")

    starter_missing_images = 0
    starter_image_dir = args.release_dir / "starter_5k" / "images"
    for row in starter_rows:
        if not (starter_image_dir / str(row["file_name"])).is_file():
            starter_missing_images += 1
    if starter_missing_images:
        errors.append("STARTER_MISSING_IMAGE_FILES")

    expected_text_rows = len(rows)
    expected_starter_rows = len(starter_rows)
    line_counts = {
        "metadata_csv": _data_line_count(args.release_dir / "metadata.csv") - 1,
        "captions_jsonl": _data_line_count(args.release_dir / "captions.jsonl"),
        "splits_csv": _data_line_count(args.release_dir / "splits.csv") - 1,
        "starter_metadata_csv": _data_line_count(args.release_dir / "starter_5k" / "metadata.csv")
        - 1,
        "starter_captions_jsonl": _data_line_count(
            args.release_dir / "starter_5k" / "captions.jsonl"
        ),
        "starter_splits_csv": _data_line_count(args.release_dir / "starter_5k" / "splits.csv")
        - 1,
    }
    for key in ("metadata_csv", "captions_jsonl", "splits_csv"):
        if line_counts[key] != expected_text_rows:
            errors.append(f"{key.upper()}_ROW_COUNT_MISMATCH")
    for key in ("starter_metadata_csv", "starter_captions_jsonl", "starter_splits_csv"):
        if line_counts[key] != expected_starter_rows:
            errors.append(f"{key.upper()}_ROW_COUNT_MISMATCH")

    required_docs = [
        "README.md",
        "SOURCES.md",
        "RIGHTS_POLICY.md",
        "DATA_DICTIONARY.md",
        "COLLECTION_REPORT.md",
        "release_manifest.json",
        "checksums.sha256",
    ]
    missing_docs = [name for name in required_docs if not (args.release_dir / name).is_file()]
    if missing_docs:
        errors.append("MISSING_REQUIRED_RELEASE_DOCUMENTS")

    checksum_checked, checksum_failures = _verify_checksums(
        args.release_dir, args.release_dir / "checksums.sha256"
    )
    if checksum_failures:
        errors.append("CHECKSUM_VALIDATION_FAILURE")

    release_bytes = sum(path.stat().st_size for path in args.release_dir.rglob("*") if path.is_file())
    release_gb = release_bytes / 1_000_000_000
    if release_gb > float(project["hard_cap_gb"]):
        errors.append("RELEASE_EXCEEDS_HARD_CAP")
    category_counts = Counter(str(row.get("category")) for row in rows)
    institution_counts = Counter(str(row.get("institution")) for row in rows)
    split_counts = Counter(str(row.get("split")) for row in rows)

    report = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "final_rows": len(rows),
        "starter_rows": len(starter_rows),
        "unique_image_ids": len(set(image_ids)),
        "unique_file_names": len(set(file_names)),
        "missing_source_url": missing_source,
        "missing_object_id": missing_object,
        "non_cc0_rights": bad_rights,
        "usable_text_ratio": usable_text_ratio,
        "object_split_leakage": leakage,
        "starter_object_split_leakage": starter_leakage,
        "starter_not_subset_rows": len(starter_not_subset),
        "missing_images": missing_images,
        "starter_missing_images": starter_missing_images,
        "decode_failures": decode_failures,
        "dimension_mismatches": dimension_mismatches,
        "line_counts": line_counts,
        "missing_required_documents": missing_docs,
        "checksum_files_checked": checksum_checked,
        "checksum_failures": checksum_failures,
        "total_image_bytes": total_image_bytes,
        "release_bytes": release_bytes,
        "release_gb": release_gb,
        "target_package_gb": float(project["target_package_gb"]),
        "hard_cap_gb": float(project["hard_cap_gb"]),
        "category_distribution": dict(category_counts),
        "institution_distribution": dict(institution_counts),
        "split_distribution": dict(split_counts),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
