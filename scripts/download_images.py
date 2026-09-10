#!/usr/bin/env python3
"""Resume-safe Phase 6 production image collection after the Phase 5 gate passes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smithsonian_image_text.downloader import download_and_process  # noqa: E402


def _identity(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("object_id") or ""),
        str(row.get("media_id") or ""),
        str(row.get("media_url") or ""),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assign_image_ids(rows: list[dict]) -> list[dict]:
    """Assign stable production IDs from the deterministic Phase 4 selection hash."""
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            str(row.get("selection_hash") or ""),
            str(row.get("object_id") or ""),
            str(row.get("media_id") or ""),
            str(row.get("media_url") or ""),
        ),
    )
    for image_id, row in enumerate(ordered, 1):
        row["image_id"] = image_id
        row["file_name"] = f"{image_id:08d}.jpg"
    return ordered


def _read_checkpoint(path: Path) -> dict[int, dict]:
    latest: dict[int, dict] = {}
    if not path.exists():
        return latest
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid checkpoint JSON at line {line_number}") from exc
            latest[int(row["image_id"])] = row
    return latest


def _valid_success(row: dict, output_dir: Path) -> bool:
    if row.get("status") != "success":
        return False
    path = output_dir / str(row.get("file_name") or "")
    if not path.is_file():
        return False
    expected = row.get("final_bytes")
    return expected is None or path.stat().st_size == int(expected)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        if not fields:
            return
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _load_pilot_reuse(
    manifest_path: Path, image_dir: Path
) -> dict[tuple[str, str, str], tuple[dict, Path]]:
    if not manifest_path.exists() or not image_dir.exists():
        return {}
    result: dict[tuple[str, str, str], tuple[dict, Path]] = {}
    for row in pq.read_table(manifest_path).to_pylist():
        if row.get("status") != "success":
            continue
        source = image_dir / str(row.get("file_name") or "")
        if source.is_file() and source.stat().st_size == int(row.get("final_bytes") or -1):
            result[_identity(row)] = (row, source)
    return result


def _reuse_pilot_row(
    candidate: dict, image_id: int, source_row: dict, source_path: Path, output_dir: Path
) -> dict:
    destination = output_dir / f"{image_id:08d}.jpg"
    started = time.perf_counter()
    if _sha256_file(source_path) != source_row.get("sha256"):
        raise ValueError(f"Pilot reuse SHA256 mismatch: {source_path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.unlink(missing_ok=True)
    shutil.copy2(source_path, partial)
    os.replace(partial, destination)
    result = dict(source_row)
    result.update(
        {
            "image_id": image_id,
            "file_name": destination.name,
            "object_id": candidate.get("object_id"),
            "media_id": candidate.get("media_id"),
            "unit_code": candidate.get("unit_code"),
            "institution": candidate.get("institution"),
            "category": candidate.get("category"),
            "category_code": candidate.get("category_code"),
            "source_url": candidate.get("source_url"),
            "media_url": candidate.get("media_url"),
            "image_url": candidate.get("image_url"),
            "attempts": 0,
            "download_seconds": 0.0,
            "processing_seconds": 0.0,
            "total_seconds": time.perf_counter() - started,
            "reuse_source": "phase5_pilot",
        }
    )
    return result


def _append_checkpoint(stream, row: dict, *, fsync: bool) -> None:
    stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    stream.flush()
    if fsync:
        os.fsync(stream.fileno())


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
        "--output-dir", type=Path, default=ROOT / "data" / "images" / "production"
    )
    parser.add_argument(
        "--candidate-manifest",
        type=Path,
        default=ROOT / "data" / "interim" / "production_candidates.parquet",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=ROOT / "data" / "audits" / "production_checkpoint.jsonl",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "audits" / "production_manifest.parquet",
    )
    parser.add_argument(
        "--manifest-csv",
        type=Path,
        default=ROOT / "data" / "audits" / "production_manifest.csv",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "data" / "audits" / "production_report.json",
    )
    parser.add_argument(
        "--pilot-manifest",
        type=Path,
        default=ROOT / "data" / "audits" / "pilot_manifest.parquet",
    )
    parser.add_argument(
        "--pilot-image-dir", type=Path, default=ROOT / "data" / "images" / "pilot"
    )
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--max-new",
        type=int,
        default=None,
        help="Process at most this many unresolved rows in this invocation; useful for smoke/resume tests.",
    )
    parser.add_argument("--no-pilot-reuse", action="store_true")
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    project = config["project"]
    pilot = config["pilot"]
    production = config["production"]
    workers = args.workers if args.workers is not None else int(production["workers"])
    if workers <= 0:
        raise SystemExit("--workers must be positive")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")
    if args.max_new is not None and args.max_new <= 0:
        raise SystemExit("--max-new must be positive")

    selected = assign_image_ids(pq.read_table(args.input).to_pylist())
    if args.limit is not None:
        selected = selected[: args.limit]
    expected_identities = [_identity(row) for row in selected]

    args.candidate_manifest.parent.mkdir(parents=True, exist_ok=True)
    if args.candidate_manifest.exists():
        existing_candidates = pq.read_table(args.candidate_manifest).to_pylist()
        if [_identity(row) for row in existing_candidates] != expected_identities:
            raise SystemExit("Existing production candidate manifest does not match current selection")
    else:
        pq.write_table(pa.Table.from_pylist(selected), args.candidate_manifest, compression="zstd")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = _read_checkpoint(args.checkpoint)
    by_id = {int(row["image_id"]): row for row in selected}
    for image_id, row in checkpoint.items():
        candidate = by_id.get(image_id)
        if candidate is None or _identity(candidate) != _identity(row):
            raise SystemExit(f"Checkpoint row {image_id} does not match current selection")

    completed_ids = {
        image_id
        for image_id, row in checkpoint.items()
        if _valid_success(row, args.output_dir)
    }
    unresolved = [row for row in selected if int(row["image_id"]) not in completed_ids]

    pilot_reuse = (
        {}
        if args.no_pilot_reuse
        else _load_pilot_reuse(args.pilot_manifest, args.pilot_image_dir)
    )
    reuse_rows: list[dict] = []
    network_rows: list[dict] = []
    for candidate in unresolved:
        if _identity(candidate) in pilot_reuse:
            reuse_rows.append(candidate)
        else:
            network_rows.append(candidate)

    if args.max_new is not None:
        budget = args.max_new
        reuse_rows = reuse_rows[:budget]
        budget -= len(reuse_rows)
        network_rows = network_rows[: max(0, budget)]

    started = time.perf_counter()
    completed_this_run = 0
    reused_this_run = 0
    network_success_this_run = 0
    checkpoint_every = max(1, int(production["checkpoint_every"]))
    with args.checkpoint.open("a", encoding="utf-8", newline="\n") as checkpoint_stream:
        for candidate in reuse_rows:
            pilot_row, pilot_path = pilot_reuse[_identity(candidate)]
            result = _reuse_pilot_row(
                candidate, int(candidate["image_id"]), pilot_row, pilot_path, args.output_dir
            )
            completed_this_run += 1
            reused_this_run += 1
            checkpoint[int(candidate["image_id"])] = result
            _append_checkpoint(
                checkpoint_stream, result, fsync=completed_this_run % checkpoint_every == 0
            )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    download_and_process,
                    candidate,
                    image_id=int(candidate["image_id"]),
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
                ): candidate
                for candidate in network_rows
            }
            for future in as_completed(futures):
                candidate = futures[future]
                result = future.result()
                result["reuse_source"] = None
                completed_this_run += 1
                if result.get("status") == "success":
                    network_success_this_run += 1
                checkpoint[int(candidate["image_id"])] = result
                _append_checkpoint(
                    checkpoint_stream, result, fsync=completed_this_run % checkpoint_every == 0
                )
                if completed_this_run % 250 == 0:
                    current_success = sum(
                        1
                        for image_id, row in checkpoint.items()
                        if image_id in by_id and _valid_success(row, args.output_dir)
                    )
                    print(
                        f"progress {completed_this_run}/{len(reuse_rows) + len(network_rows)} "
                        f"this-run; {current_success}/{len(selected)} valid success",
                        flush=True,
                    )
        checkpoint_stream.flush()
        os.fsync(checkpoint_stream.fileno())

    wall_seconds = time.perf_counter() - started
    latest = _read_checkpoint(args.checkpoint)
    valid_success_rows = [
        latest[image_id]
        for image_id in sorted(by_id)
        if image_id in latest and _valid_success(latest[image_id], args.output_dir)
    ]
    failed_rows = [
        latest[image_id]
        for image_id in sorted(by_id)
        if image_id in latest and latest[image_id].get("status") != "success"
    ]
    success_ids = {int(row["image_id"]) for row in valid_success_rows}
    pending_ids = [image_id for image_id in sorted(by_id) if image_id not in success_ids and image_id not in latest]

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest_rows = [latest[image_id] for image_id in sorted(by_id) if image_id in latest]
    if manifest_rows:
        pq.write_table(pa.Table.from_pylist(manifest_rows), args.manifest, compression="zstd")
        _write_csv(args.manifest_csv, manifest_rows)

    total_image_bytes = sum(int(row.get("final_bytes") or 0) for row in valid_success_rows)
    metadata_bytes = args.candidate_manifest.stat().st_size
    package_gb = (total_image_bytes + metadata_bytes) / 1_000_000_000
    category_success = Counter(str(row.get("category_code")) for row in valid_success_rows)
    institution_success = Counter(str(row.get("institution")) for row in valid_success_rows)
    error_counts = Counter(str(row.get("error")) for row in failed_rows)
    report = {
        "mode": "phase6_production_download",
        "candidate_rows": len(selected),
        "valid_success_rows": len(valid_success_rows),
        "latest_failure_rows": len(failed_rows),
        "pending_rows": len(pending_ids),
        "completed_this_run": completed_this_run,
        "pilot_reused_this_run": reused_this_run,
        "network_success_this_run": network_success_this_run,
        "workers": workers,
        "wall_seconds_this_run": wall_seconds,
        "total_final_image_bytes": total_image_bytes,
        "candidate_metadata_bytes": metadata_bytes,
        "current_package_gb": package_gb,
        "target_package_gb": float(project["target_package_gb"]),
        "hard_cap_gb": float(project["hard_cap_gb"]),
        "category_success": dict(category_success),
        "institution_success": dict(institution_success),
        "error_counts": dict(error_counts),
        "output_dir": str(args.output_dir),
        "candidate_manifest": str(args.candidate_manifest),
        "checkpoint": str(args.checkpoint),
        "manifest": str(args.manifest),
        "manifest_csv": str(args.manifest_csv),
        "complete": len(valid_success_rows) + len(failed_rows) == len(selected) and not pending_ids,
        "all_candidates_successful": len(valid_success_rows) == len(selected),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.max_new is not None:
        return 0
    return 0 if report["all_candidates_successful"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
