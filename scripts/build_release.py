#!/usr/bin/env python3
"""Build the local Kaggle-ready release tree without publishing it."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = fields or (list(rows[0]) if rows else [])
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        if not fieldnames:
            return
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _predicted_checksum_bytes(output_dir: Path, targets: list[Path]) -> int:
    """Return exact ASCII byte size of checksums.sha256 before hashing file contents."""
    total = 0
    for path in targets:
        relative = path.relative_to(output_dir).as_posix()
        total += len(("0" * 64 + "  " + relative + "\n").encode("ascii"))
    return total


def _git_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_readme(path: Path, *, final_count: int, starter_count: int) -> None:
    text = f"""# 25K Museum Images with Captions

CC0 Smithsonian images and authoritative metadata for computer vision, CLIP and VLM workflows.

This release contains **{final_count:,}** cleaned 2D image-text rows plus a **{starter_count:,}**-image
starter subset. Images are normalized to a maximum side of 512 px. The `model_text` field is
deterministically composed from Smithsonian metadata; it is not an LLM-generated or claimed
human-written visual caption.

## Files

- `images/`: normalized JPEGs.
- `metadata.parquet`: canonical full metadata (recommended).
- `metadata.csv`: convenience table.
- `captions.jsonl`: image IDs, filenames, and model-ready text.
- `splits.csv`: object-level leakage-safe train/validation/test split assignments.
- `starter_5k/`: balanced starter subset using the same schema and split assignments.
- `SOURCES.md`, `RIGHTS_POLICY.md`, `DATA_DICTIONARY.md`: source, rights, and field documentation.
- `release_manifest.json` and `checksums.sha256`: release audit information.

## Rights

Automatic inclusion required both record-level Smithsonian metadata access **CC0** and the exact
selected image media item access **CC0**. Ambiguous rights and sensitive-review candidates were not
automatically released. CC0 addresses copyright; other rights such as privacy, publicity, trademark,
or culturally sensitive use can still require consideration. See `RIGHTS_POLICY.md`.

## Splits

Rows from the same Smithsonian `object_id` are always assigned to the same split, so front/back/side
views of one object cannot leak across train, validation, and test.
"""
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata",
        type=Path,
        default=ROOT / "data" / "interim" / "metadata_final.parquet",
    )
    parser.add_argument(
        "--starter", type=Path, default=ROOT / "data" / "interim" / "starter_5k.parquet"
    )
    parser.add_argument(
        "--image-dir", type=Path, default=ROOT / "data" / "images" / "production"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "data" / "release" / "museum-images"
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "collection.yaml")
    parser.add_argument(
        "--discovery-report",
        type=Path,
        default=ROOT / "data" / "audits" / "discovery_report.json",
    )
    parser.add_argument(
        "--sampling-report",
        type=Path,
        default=ROOT / "data" / "audits" / "sampling_report.json",
    )
    parser.add_argument(
        "--pilot-report", type=Path, default=ROOT / "data" / "audits" / "pilot_report.json"
    )
    parser.add_argument(
        "--qa-report",
        type=Path,
        default=ROOT / "data" / "audits" / "image_quality_report.json",
    )
    parser.add_argument(
        "--snapshot-manifest",
        type=Path,
        default=ROOT / "data" / "audits" / "local_snapshot_manifest.json",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if args.output_dir.exists():
        if not args.force:
            raise SystemExit(f"Release directory exists; use --force to rebuild: {args.output_dir}")
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True)

    rows = pq.read_table(args.metadata).to_pylist()
    starter_rows = pq.read_table(args.starter).to_pylist()
    release_images = args.output_dir / "images"
    for index, row in enumerate(rows, 1):
        source = args.image_dir / str(row["file_name"])
        if not source.is_file():
            raise FileNotFoundError(source)
        _link_or_copy(source, release_images / str(row["file_name"]))
        if index % 5000 == 0:
            print(f"release image links {index}/{len(rows)}", flush=True)

    shutil.copy2(args.metadata, args.output_dir / "metadata.parquet")
    _write_csv(args.output_dir / "metadata.csv", rows)
    with (args.output_dir / "captions.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            payload = {
                "image_id": row["image_id"],
                "file_name": row["file_name"],
                "object_id": row["object_id"],
                "model_text": row["model_text"],
                "text_source": row["text_source"],
            }
            stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    _write_csv(
        args.output_dir / "splits.csv",
        rows,
        ["image_id", "object_id", "file_name", "category", "split"],
    )

    starter_dir = args.output_dir / "starter_5k"
    starter_dir.mkdir(parents=True)
    shutil.copy2(args.starter, starter_dir / "metadata.parquet")
    _write_csv(starter_dir / "metadata.csv", starter_rows)
    _write_csv(
        starter_dir / "splits.csv",
        starter_rows,
        ["image_id", "object_id", "file_name", "category", "split"],
    )
    with (starter_dir / "captions.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in starter_rows:
            stream.write(
                json.dumps(
                    {
                        "image_id": row["image_id"],
                        "file_name": row["file_name"],
                        "object_id": row["object_id"],
                        "model_text": row["model_text"],
                        "text_source": row["text_source"],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
    for row in starter_rows:
        source = release_images / str(row["file_name"])
        _link_or_copy(source, starter_dir / "images" / str(row["file_name"]))

    for source_name in (
        "SOURCES.md",
        "RIGHTS_POLICY.md",
        "DATA_DICTIONARY.md",
        "COLLECTION_REPORT.md",
        "KAGGLE_PAGE.md",
        "DISTRIBUTION.md",
    ):
        shutil.copy2(ROOT / "docs" / source_name, args.output_dir / source_name)
    example_notebook = ROOT / "notebooks" / "starter_eda.ipynb"
    if example_notebook.is_file():
        examples_dir = args.output_dir / "examples"
        examples_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(example_notebook, examples_dir / example_notebook.name)
    if args.snapshot_manifest.is_file():
        provenance_dir = args.output_dir / "provenance"
        provenance_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.snapshot_manifest, provenance_dir / args.snapshot_manifest.name)
    _write_readme(args.output_dir / "README.md", final_count=len(rows), starter_count=len(starter_rows))

    image_bytes = sum((release_images / str(row["file_name"])).stat().st_size for row in rows)
    starter_image_bytes = sum(
        (starter_dir / "images" / str(row["file_name"])).stat().st_size for row in starter_rows
    )
    category_counts = Counter(str(row.get("category")) for row in rows)
    institution_counts = Counter(str(row.get("institution")) for row in rows)
    split_counts = Counter(str(row.get("split")) for row in rows)
    non_image_bytes = sum(
        path.stat().st_size
        for path in args.output_dir.rglob("*")
        if path.is_file() and "images" not in path.parts
    )
    discovery_report = _load_json(args.discovery_report)
    sampling_report = _load_json(args.sampling_report)
    pilot_report = _load_json(args.pilot_report)
    qa_report = _load_json(args.qa_report)
    eligibility = discovery_report.get("eligibility_status") or {}
    manifest = {
        "dataset_version": "1.0.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_count": discovery_report.get("rows"),
        "eligible_count": eligibility.get("eligible"),
        "review_required_count": eligibility.get("review_required"),
        "rejected_count": eligibility.get("rejected"),
        "selected_count": sampling_report.get(
            "selected_rows", int(config["project"]["target_final_images"])
        ),
        "final_image_count": len(rows),
        "starter_image_count": len(starter_rows),
        "category_distribution": dict(category_counts),
        "institution_distribution": dict(institution_counts),
        "split_distribution": dict(split_counts),
        "total_image_bytes": image_bytes,
        "starter_image_bytes": starter_image_bytes,
        "non_image_bytes_before_manifest_and_checksums": non_image_bytes,
        "apparent_release_bytes": None,
        "apparent_release_gb": None,
        "pipeline_git_commit": _git_commit(),
        "image_max_side_px": int(config["project"]["max_side_px"]),
        "rights": "CC0 media + CC0 metadata automatic inclusion gate",
        "phase5_pilot": {
            "attempted": pilot_report.get("attempted_rows"),
            "success_rate": pilot_report.get("success_rate"),
            "expected_25k_package_gb": pilot_report.get("expected_25k_package_gb"),
            "package_gate": pilot_report.get("package_gate"),
        },
        "image_qa": {
            "qa_keep_rows": qa_report.get("qa_keep_rows"),
            "qa_exclude_rows": qa_report.get("qa_exclude_rows"),
            "exact_duplicate_rows_dropped": qa_report.get("exact_duplicate_rows_dropped"),
            "near_duplicate_candidate_pairs": qa_report.get("near_duplicate_candidate_pairs"),
        },
        "checksums_file": "checksums.sha256",
    }
    manifest_path = args.output_dir / "release_manifest.json"
    checksum_path = args.output_dir / "checksums.sha256"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # The checksum file is excluded from its own hash list, and each checksum line has a fixed-size
    # digest. That lets the manifest record the exact final apparent release size before checksums are
    # written, while still allowing release_manifest.json itself to be checksummed exactly once.
    for _ in range(5):
        checksum_targets = sorted(
            path
            for path in args.output_dir.rglob("*")
            if path.is_file() and path != checksum_path
        )
        pre_checksum_bytes = sum(path.stat().st_size for path in checksum_targets)
        predicted_checksum_bytes = _predicted_checksum_bytes(args.output_dir, checksum_targets)
        final_release_bytes = pre_checksum_bytes + predicted_checksum_bytes
        if manifest["apparent_release_bytes"] == final_release_bytes:
            break
        manifest["apparent_release_bytes"] = final_release_bytes
        manifest["apparent_release_gb"] = final_release_bytes / 1_000_000_000
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    else:
        raise RuntimeError("Release size manifest did not converge")

    checksum_targets = sorted(
        path
        for path in args.output_dir.rglob("*")
        if path.is_file() and path != checksum_path
    )
    with checksum_path.open("w", encoding="ascii", newline="\n") as stream:
        for index, path in enumerate(checksum_targets, 1):
            stream.write(f"{_sha256(path)}  {path.relative_to(args.output_dir).as_posix()}\n")
            if index % 5000 == 0:
                print(f"checksums {index}/{len(checksum_targets)}", flush=True)

    actual_release_bytes = sum(
        path.stat().st_size for path in args.output_dir.rglob("*") if path.is_file()
    )
    if actual_release_bytes != manifest["apparent_release_bytes"]:
        raise RuntimeError(
            "Final release byte count differs from manifest: "
            f"actual={actual_release_bytes} manifest={manifest['apparent_release_bytes']}"
        )

    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
