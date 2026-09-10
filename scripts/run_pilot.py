#!/usr/bin/env python3
"""Run the category-balanced Phase 5 image pilot and calculate the production size/time gate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smithsonian_image_text.downloader import download_and_process  # noqa: E402


def _rank(seed: str, row: dict) -> str:
    identity = "|".join(
        [
            str(row.get("object_id") or ""),
            str(row.get("media_id") or ""),
            str(row.get("media_url") or ""),
        ]
    )
    return hashlib.sha256(f"{seed}:{identity}".encode()).hexdigest()


def proportional_counts(quotas: dict[str, int], limit: int) -> dict[str, int]:
    """Allocate an exact pilot size using largest-remainder proportional allocation."""
    if limit <= 0:
        raise ValueError("pilot limit must be positive")
    total = sum(quotas.values())
    if total <= 0 or limit > total:
        raise ValueError("pilot limit must not exceed the positive selection quota total")
    exact = {key: limit * value / total for key, value in quotas.items()}
    result = {key: math.floor(value) for key, value in exact.items()}
    remaining = limit - sum(result.values())
    priority = sorted(quotas, key=lambda key: (-(exact[key] - result[key]), key))
    for key in priority[:remaining]:
        result[key] += 1
    return result


def choose_pilot(rows: list[dict], *, counts: dict[str, int], seed: str) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for source in rows:
        row = dict(source)
        category = str(row.get("category_code") or "")
        row["pilot_hash"] = _rank(seed, row)
        grouped[category].append(row)

    selected: list[dict] = []
    for category, count in counts.items():
        available = sorted(grouped.get(category, []), key=lambda row: row["pilot_hash"])
        if len(available) < count:
            raise ValueError(
                f"Pilot category {category} has {len(available)} rows, below requested {count}"
            )
        selected.extend(available[:count])
    selected.sort(key=lambda row: row["pilot_hash"])
    return selected


def _stats(values: list[float | int]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "min": None, "max": None}
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": len(values),
        "mean": float(np.mean(array)),
        "p50": float(np.percentile(array, 50)),
        "p95": float(np.percentile(array, 95)),
        "min": float(np.min(array)),
        "max": float(np.max(array)),
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        if not fields:
            return
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "interim" / "selected_candidates.parquet",
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "collection.yaml")
    parser.add_argument(
        "--category-config", type=Path, default=ROOT / "config" / "category_mapping.yaml"
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "data" / "images" / "pilot"
    )
    parser.add_argument(
        "--pilot-candidates",
        type=Path,
        default=ROOT / "data" / "interim" / "pilot_candidates.parquet",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "audits" / "pilot_manifest.parquet",
    )
    parser.add_argument(
        "--manifest-csv",
        type=Path,
        default=ROOT / "data" / "audits" / "pilot_manifest.csv",
    )
    parser.add_argument(
        "--report", type=Path, default=ROOT / "data" / "audits" / "pilot_report.json"
    )
    parser.add_argument(
        "--exact-duplicates",
        type=Path,
        default=ROOT / "data" / "audits" / "pilot_exact_duplicates.csv",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    collection = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    category_config = yaml.safe_load(args.category_config.read_text(encoding="utf-8"))
    pilot = collection["pilot"]
    project = collection["project"]
    selection = category_config["selection"]
    limit = args.limit if args.limit is not None else int(pilot["images"])
    workers = args.workers if args.workers is not None else int(pilot["workers"])
    if workers <= 0:
        raise SystemExit("--workers must be positive")
    if limit <= 0:
        raise SystemExit("--limit must be positive")

    outputs = [args.pilot_candidates, args.manifest, args.manifest_csv, args.report]
    if not args.dry_run:
        outputs.append(args.exact_duplicates)
    existing = [path for path in outputs if path.exists()]
    if args.output_dir.exists() and any(args.output_dir.glob("*.jpg")):
        existing.append(args.output_dir)
    if existing and not args.force:
        raise SystemExit(
            "Refusing to overwrite existing pilot outputs without --force: "
            + ", ".join(str(path) for path in existing)
        )
    if args.force and args.output_dir.exists():
        shutil.rmtree(args.output_dir)

    rows = pq.read_table(args.input).to_pylist()
    quotas = {str(key): int(value) for key, value in selection["quotas"].items()}
    counts = proportional_counts(quotas, limit)
    selected = choose_pilot(rows, counts=counts, seed=str(pilot["deterministic_seed"]))
    args.pilot_candidates.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(selected), args.pilot_candidates, compression="zstd")

    if args.dry_run:
        report = {
            "mode": "pilot_dry_run",
            "requested_rows": limit,
            "selected_rows": len(selected),
            "category_counts": dict(Counter(str(row["category_code"]) for row in selected)),
            "pilot_candidates": str(args.pilot_candidates),
            "image_bytes_read": 0,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                download_and_process,
                candidate,
                image_id=image_id,
                output_dir=args.output_dir,
                max_side=int(project["max_side_px"]),
                jpeg_quality=int(pilot["jpeg_quality"]),
                timeout=float(pilot["request_timeout_seconds"]),
                max_attempts=int(pilot["max_attempts"]),
                retry_backoff_seconds=float(pilot["retry_backoff_seconds"]),
                max_download_bytes=int(pilot["max_download_bytes"]),
                phash_size=int(pilot["phash_size"]),
                phash_highfreq_factor=int(pilot["phash_highfreq_factor"]),
                min_max_side=int(pilot["min_max_side_px"]),
            ): image_id
            for image_id, candidate in enumerate(selected, 1)
        }
        for future in as_completed(futures):
            results.append(future.result())
    wall_seconds = time.perf_counter() - started
    results.sort(key=lambda row: int(row["image_id"]))

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(results), args.manifest, compression="zstd")
    _write_csv(args.manifest_csv, results)

    successes = [row for row in results if row["status"] == "success"]
    failures = [row for row in results if row["status"] != "success"]
    http_counts = Counter(str(row.get("http_status")) for row in results)
    error_counts = Counter(str(row.get("error")) for row in failures)
    category_success = Counter(str(row.get("category_code")) for row in successes)
    category_failure = Counter(str(row.get("category_code")) for row in failures)

    exact_groups: dict[str, list[dict]] = defaultdict(list)
    for row in successes:
        exact_groups[str(row["sha256"])].append(row)
    duplicate_rows: list[dict] = []
    for digest, group in exact_groups.items():
        if len(group) <= 1:
            continue
        for row in group:
            duplicate_rows.append(
                {
                    "sha256": digest,
                    "image_id": row["image_id"],
                    "object_id": row["object_id"],
                    "media_id": row["media_id"],
                    "category": row["category"],
                    "file_name": row["file_name"],
                }
            )
    _write_csv(args.exact_duplicates, duplicate_rows)

    final_bytes = [int(row["final_bytes"]) for row in successes]
    download_bytes = [int(row["download_bytes"]) for row in successes]
    download_seconds = [float(row["download_seconds"]) for row in successes]
    processing_seconds = [float(row["processing_seconds"]) for row in successes]
    target_final_images = int(project["target_final_images"])
    expected_image_bytes = (
        float(np.mean(final_bytes)) * target_final_images if final_bytes else float("inf")
    )
    metadata_bytes = args.input.stat().st_size
    expected_package_bytes = expected_image_bytes + metadata_bytes
    expected_package_gb = expected_package_bytes / 1_000_000_000
    if expected_package_gb <= float(project["target_package_gb"]):
        package_gate = "GO"
    elif expected_package_gb <= float(project["hard_cap_gb"]):
        package_gate = "ADJUST"
    else:
        package_gate = "STOP"

    decode_failures = sum(
        1 for row in failures if row.get("http_status") == 200 and not row.get("decode_success")
    )
    report = {
        "mode": "phase5_image_pilot",
        "requested_rows": limit,
        "attempted_rows": len(results),
        "success_rows": len(successes),
        "failure_rows": len(failures),
        "success_rate": round(len(successes) / len(results), 6) if results else 0.0,
        "http_status_counts": dict(http_counts),
        "error_counts": dict(error_counts),
        "http_404_rows": sum(1 for row in failures if row.get("http_status") == 404),
        "decode_failure_rows": decode_failures,
        "decode_failure_rate": round(decode_failures / len(results), 6) if results else 0.0,
        "category_requested": counts,
        "category_success": dict(category_success),
        "category_failure": dict(category_failure),
        "download_bytes": _stats(download_bytes),
        "final_bytes": _stats(final_bytes),
        "download_seconds": _stats(download_seconds),
        "processing_seconds": _stats(processing_seconds),
        "wall_seconds": wall_seconds,
        "workers": workers,
        "expected_25k_image_bytes": expected_image_bytes if final_bytes else None,
        "selected_metadata_bytes": metadata_bytes,
        "expected_25k_package_gb": expected_package_gb if final_bytes else None,
        "expected_full_runtime_hours_same_concurrency": (
            wall_seconds * target_final_images / len(results) / 3600 if results else None
        ),
        "target_final_average_kb": "100-150",
        "observed_final_average_kb": (
            float(np.mean(final_bytes)) / 1000 if final_bytes else None
        ),
        "package_gate": package_gate,
        "target_package_gb": float(project["target_package_gb"]),
        "hard_cap_gb": float(project["hard_cap_gb"]),
        "exact_duplicate_groups": sum(1 for group in exact_groups.values() if len(group) > 1),
        "exact_duplicate_rows": len(duplicate_rows),
        "pilot_candidates": str(args.pilot_candidates),
        "manifest": str(args.manifest),
        "manifest_csv": str(args.manifest_csv),
        "image_dir": str(args.output_dir),
        "exact_duplicates_csv": str(args.exact_duplicates),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if package_gate != "STOP" else 2


if __name__ == "__main__":
    raise SystemExit(main())
