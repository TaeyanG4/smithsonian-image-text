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

KAGGLE_TITLE = "Smithsonian 25K Museum Image-Text Dataset"
KAGGLE_SUBTITLE = "24,972 CC0 images, rich metadata, leakage-safe splits and a 5K starter set"
KAGGLE_ID = "taeyangg4/smithsonian-25k-museum-image-text"
KAGGLE_CONTROL_FILES = {
    "dataset-metadata.json",
    "dataset-cover-image.jpg",
    "dataset-cover-image.jpeg",
    "dataset-cover-image.png",
    "dataset-cover-image.webp",
}

KAGGLE_FIELD_DESCRIPTIONS = {
    "image_id": "Stable integer image identifier assigned by this release pipeline.",
    "object_id": "Stable Smithsonian object grouping key; all views of one object stay in one split.",
    "media_id": "Identifier for the individual Smithsonian media item / image view.",
    "file_name": "Normalized JPEG filename inside images/ or images.zip.",
    "title": "Authoritative Smithsonian object title/name when available.",
    "description": "Authoritative Smithsonian descriptive text when available.",
    "model_text": "Deterministic <=512-character composition of Smithsonian metadata for model input.",
    "text_source": "Provenance label for model_text; fixed to smithsonian_metadata_composed in V1.",
    "category": "Human-readable broad sampling category assigned deterministically by this project.",
    "category_code": "Machine-friendly code for the broad project sampling category.",
    "object_type": "Smithsonian object/type terms.",
    "institution": "Smithsonian owning/source institution or unit name.",
    "collection": "Smithsonian collection/set name when available.",
    "creator": "Creator, maker, artist, or equivalent source role when available.",
    "related_names": "Other authoritative related names from Smithsonian metadata.",
    "date": "Authoritative source date text; intentionally not forced to ISO format.",
    "place": "Place terms from Smithsonian metadata when available.",
    "topics": "Topic terms from Smithsonian metadata when available.",
    "culture": "Culture terms from Smithsonian metadata when available.",
    "scientific_name": "Scientific or taxonomic name when supplied by Smithsonian.",
    "physical_description": "Physical description, medium, or materials text when available.",
    "credit_line": "Smithsonian credit line when available.",
    "media_caption": "Smithsonian-supplied media caption when present.",
    "alt_text": "Smithsonian accessibility alt text when present.",
    "media_description": "Smithsonian media-level extended accessibility description when present.",
    "width": "Final normalized JPEG width in pixels.",
    "height": "Final normalized JPEG height in pixels.",
    "aspect_ratio": "Final image width divided by height.",
    "source_url": "Official Smithsonian object/source URL.",
    "media_url": "Official media content URL exactly as supplied by Smithsonian.",
    "image_url": "Preferred approximately 512 px Smithsonian image request URL used for collection.",
    "rights": "Convenience rights value; CC0 for every released V1 row.",
    "metadata_rights": "Record metadata usage access value; must be exact CC0 for automatic inclusion.",
    "media_rights": "Exact selected media usage access value; must be exact CC0 for automatic inclusion.",
    "object_rights": "Additional object-rights statements supplied in Smithsonian free text.",
    "record_guid": "Smithsonian object ARK/GUID when present.",
    "media_guid": "Smithsonian media ARK/GUID when present.",
    "unit_code": "Smithsonian source unit code.",
    "sha256": "SHA-256 checksum of the final normalized JPEG bytes.",
    "phash": "64-bit DCT perceptual hash encoded as 16 hexadecimal characters.",
    "final_bytes": "Final normalized JPEG size in bytes.",
    "qa_flags": "Non-fatal image QA review flags; blank when none apply.",
    "split": "Leakage-safe train, validation, or test split assigned at object_id group level.",
}


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
    text = f"""# Smithsonian 25K Museum Image-Text Dataset

CC0 Smithsonian images and authoritative metadata for computer vision and multimodal workflows.

This release contains **{final_count:,}** cleaned 2D image-text rows plus a **{starter_count:,}**-image
starter subset. Images are normalized to a maximum side of 512 px. The `model_text` field is
deterministically composed from Smithsonian metadata; it is not an LLM-generated or claimed
human-written visual caption.

## Files

- `images/`: normalized JPEGs.
- `metadata.parquet`: canonical full metadata (recommended).
- `starter_5k/`: balanced 5,000-image starter subset with its canonical Parquet metadata.
- `exports/`: optional CSV/JSONL/split convenience exports derived from `metadata.parquet`.
- `docs/`: source, rights, data-dictionary, distribution, and collection-QA documentation.
- `provenance/`: release manifest, checksums, and the pinned source-snapshot manifest.

CLIP embeddings are intentionally **not** part of the base V1 package. The repository contains an
optional builder and side-artifact strategy so model-derived features can be versioned independently
without inflating or coupling the canonical image release.

## Rights

Automatic inclusion required both record-level Smithsonian metadata access **CC0** and the exact
selected image media item access **CC0**. Ambiguous rights and sensitive-review candidates were not
automatically released. CC0 addresses copyright; other rights such as privacy, publicity, trademark,
or culturally sensitive use can still require consideration. See `docs/RIGHTS_POLICY.md`.

## Splits

Rows from the same Smithsonian `object_id` are always assigned to the same split, so front/back/side
views of one object cannot leak across train, validation, and test.
"""
    path.write_text(text, encoding="utf-8")


def _kaggle_type(field_type: str) -> str:
    if field_type.startswith("int"):
        return "integer"
    if field_type in {"double", "float", "float32", "float64"}:
        return "numeric"
    return "string"


def _table_schema_fields(table_path: Path, fields: list[str] | None = None) -> list[dict[str, str]]:
    schema = pq.read_schema(table_path)
    selected = set(fields) if fields is not None else None
    result: list[dict[str, str]] = []
    for field in schema:
        if selected is not None and field.name not in selected:
            continue
        result.append(
            {
                "name": field.name,
                "description": KAGGLE_FIELD_DESCRIPTIONS.get(
                    field.name, "Field documented in DATA_DICTIONARY.md."
                ),
                "type": _kaggle_type(str(field.type)),
            }
        )
    return result


def _write_kaggle_metadata(
    path: Path,
    *,
    description: str,
    metadata_path: Path,
    release_root: Path,
) -> None:
    metadata_schema = _table_schema_fields(metadata_path)
    split_fields = ["image_id", "object_id", "file_name", "category", "split"]
    split_schema = [field for field in metadata_schema if field["name"] in split_fields]
    caption_fields = ["image_id", "file_name", "object_id", "model_text", "text_source"]
    caption_schema = [field for field in metadata_schema if field["name"] in caption_fields]
    all_resources = [
        {
            "path": "README.md",
            "description": "Concise release overview, file map, rights summary, and split policy.",
        },
        {
            "path": "metadata.parquet",
            "description": "Canonical metadata table for all 24,972 released image rows.",
            "schema": {"fields": metadata_schema},
        },
        {
            "path": "exports/metadata.csv",
            "description": "CSV convenience export with the same rows and columns as metadata.parquet.",
            "schema": {"fields": metadata_schema},
        },
        {
            "path": "exports/captions.jsonl",
            "description": "Compact image identifiers plus deterministic Smithsonian model_text.",
            "schema": {"fields": caption_schema},
        },
        {
            "path": "exports/splits.csv",
            "description": "Object-level leakage-safe train/validation/test assignments.",
            "schema": {"fields": split_schema},
        },
        {
            "path": "starter_5k/metadata.parquet",
            "description": "Canonical Parquet metadata for the balanced 5,000-image starter subset.",
            "schema": {"fields": metadata_schema},
        },
        {
            "path": "docs/COLLECTION_REPORT.md",
            "description": "Collection QA summary with final counts, exclusions, and category coverage.",
        },
        {
            "path": "docs/DATA_DICTIONARY.md",
            "description": "Detailed field definitions and source/derivation notes.",
        },
        {
            "path": "docs/DISTRIBUTION.md",
            "description": "Distribution notes for categories, institutions, splits, and release statistics.",
        },
        {
            "path": "docs/RIGHTS_POLICY.md",
            "description": "Exact CC0 eligibility gate and responsible-use caveats.",
        },
        {
            "path": "docs/SOURCES.md",
            "description": "Official Smithsonian source and provenance documentation.",
        },
        {
            "path": "provenance/local_snapshot_manifest.json",
            "description": "Hashes and identifiers pinning the Smithsonian metadata snapshot used for this release.",
        },
        {
            "path": "provenance/release_manifest.json",
            "description": "Machine-readable release manifest recording counts, sizes, and build provenance.",
        },
        {
            "path": "provenance/checksums.sha256",
            "description": "SHA-256 checksums for downloadable release files.",
        },
    ]

    # Kaggle version creation only matches resource metadata against files uploaded
    # directly from the release root. Directory uploads are archived first, so a
    # nested path cannot match at that stage. Keep `resources` deliberately small
    # so the two root files receive their descriptions/schema on V3 creation.
    root_resource_paths = {"README.md", "metadata.parquet"}
    root_resources = [item for item in all_resources if item["path"] in root_resource_paths]

    # Kaggle CLI 2.2.2+ also supports the DatasetSettings `data` representation on
    # metadata updates. Include exact byte sizes so the server has the strongest
    # possible identity match for extracted/nested files after the version exists.
    data_entries: list[dict[str, object]] = []
    for resource in all_resources:
        resource_path = release_root / str(resource["path"])
        if not resource_path.is_file():
            raise FileNotFoundError(resource_path)
        entry: dict[str, object] = {
            "name": str(resource["path"]),
            "description": str(resource["description"]),
            "totalBytes": int(resource_path.stat().st_size),
        }
        fields = (resource.get("schema") or {}).get("fields") or []
        if fields:
            entry["columns"] = [
                {
                    "name": str(field["name"]),
                    "description": str(field.get("description") or field.get("title") or ""),
                    "type": str(field.get("type") or "string"),
                }
                for field in fields
            ]
        data_entries.append(entry)

    payload = {
        "title": KAGGLE_TITLE,
        "subtitle": KAGGLE_SUBTITLE,
        "description": description,
        "id": KAGGLE_ID,
        "licenses": [{"name": "CC0-1.0"}],
        "keywords": ["computer vision", "art", "deep learning", "image classification", "nlp"],
        "image": "dataset-cover-image.jpg",
        "expectedUpdateFrequency": "never",
        "userSpecifiedSources": (
            "[Smithsonian Open Access](https://www.si.edu/openaccess) bulk/EDAN metadata and official "
            "Smithsonian image media. Every automatically released row requires both record metadata "
            "and the exact selected media item to report CC0 access. Stable Smithsonian identifiers, "
            "source URLs, rights fields, checksums, and build provenance are retained. Reproducible "
            "pipeline: https://github.com/TaeyanG4/smithsonian-image-text"
        ),
        "resources": root_resources,
        "data": data_entries,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


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
    parser.add_argument(
        "--clip-embeddings",
        type=Path,
        default=ROOT / "data" / "interim" / "clip_embeddings.parquet",
    )
    parser.add_argument(
        "--clip-embeddings-manifest",
        type=Path,
        default=ROOT / "data" / "audits" / "clip_embeddings_manifest.json",
    )
    parser.add_argument(
        "--include-clip-embeddings",
        action="store_true",
        help="Opt in to packaging the optional CLIP side artifact. Base V1 intentionally omits it.",
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
    exports_dir = args.output_dir / "exports"
    exports_dir.mkdir(parents=True)
    _write_csv(exports_dir / "metadata.csv", rows)
    with (exports_dir / "captions.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
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
        exports_dir / "splits.csv",
        rows,
        ["image_id", "object_id", "file_name", "category", "split"],
    )

    starter_dir = args.output_dir / "starter_5k"
    starter_dir.mkdir(parents=True)
    shutil.copy2(args.starter, starter_dir / "metadata.parquet")
    for row in starter_rows:
        source = release_images / str(row["file_name"])
        _link_or_copy(source, starter_dir / "images" / str(row["file_name"]))

    docs_dir = args.output_dir / "docs"
    docs_dir.mkdir(parents=True)
    for source_name in (
        "SOURCES.md",
        "RIGHTS_POLICY.md",
        "DATA_DICTIONARY.md",
        "COLLECTION_REPORT.md",
        "DISTRIBUTION.md",
    ):
        shutil.copy2(ROOT / "docs" / source_name, docs_dir / source_name)
    cover_source = ROOT / "docs" / "dataset-cover-image.jpg"
    if cover_source.is_file():
        shutil.copy2(cover_source, args.output_dir / "dataset-cover-image.jpg")
    if args.snapshot_manifest.is_file():
        provenance_dir = args.output_dir / "provenance"
        provenance_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.snapshot_manifest, provenance_dir / args.snapshot_manifest.name)
    clip_manifest: dict = {}
    if args.include_clip_embeddings and args.clip_embeddings.is_file():
        optional_dir = args.output_dir / "optional"
        optional_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.clip_embeddings, optional_dir / "clip_embeddings.parquet")
        if args.clip_embeddings_manifest.is_file():
            shutil.copy2(
                args.clip_embeddings_manifest,
                optional_dir / "clip_embeddings_manifest.json",
            )
            clip_manifest = _load_json(args.clip_embeddings_manifest)
    _write_readme(args.output_dir / "README.md", final_count=len(rows), starter_count=len(starter_rows))
    kaggle_description = (ROOT / "docs" / "KAGGLE_PAGE.md").read_text(encoding="utf-8")

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
        if path.is_file()
        and "images" not in path.parts
        and path.name not in KAGGLE_CONTROL_FILES
    )
    discovery_report = _load_json(args.discovery_report)
    sampling_report = _load_json(args.sampling_report)
    pilot_report = _load_json(args.pilot_report)
    qa_report = _load_json(args.qa_report)
    eligibility = discovery_report.get("eligibility_status") or {}
    manifest = {
        "dataset_version": "1.1.0",
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
        "optional_clip_embeddings": (
            {
                "included": True,
                "model_id": clip_manifest.get("model_id"),
                "model_revision": clip_manifest.get("model_revision"),
                "embedding_dimension": clip_manifest.get("embedding_dimension"),
                "embedding_dtype": clip_manifest.get("embedding_dtype"),
                "image_count": clip_manifest.get("image_count"),
                "path": "optional/clip_embeddings.parquet",
            }
            if args.include_clip_embeddings and args.clip_embeddings.is_file()
            else {"included": False}
        ),
        "checksums_file": "provenance/checksums.sha256",
    }
    provenance_dir = args.output_dir / "provenance"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = provenance_dir / "release_manifest.json"
    checksum_path = provenance_dir / "checksums.sha256"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # The checksum file is excluded from its own hash list, and each checksum line has a fixed-size
    # digest. That lets the manifest record the exact final apparent release size before checksums are
    # written, while still allowing release_manifest.json itself to be checksummed exactly once.
    for _ in range(5):
        checksum_targets = sorted(
            path
            for path in args.output_dir.rglob("*")
            if path.is_file()
            and path != checksum_path
            and path.name not in KAGGLE_CONTROL_FILES
        )
        pre_checksum_bytes = sum(path.stat().st_size for path in checksum_targets)
        predicted_checksum_bytes = _predicted_checksum_bytes(args.output_dir, checksum_targets)
        final_release_bytes = pre_checksum_bytes + predicted_checksum_bytes
        if manifest["apparent_release_bytes"] == final_release_bytes:
            break
        manifest["apparent_release_bytes"] = final_release_bytes
        # Keep the human-readable GB value at stable precision.  Serializing the
        # full float can change release_manifest.json by one byte as the exact
        # byte-count field converges, producing a two-value fixed-point cycle.
        manifest["apparent_release_gb"] = round(final_release_bytes / 1_000_000_000, 6)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    else:
        raise RuntimeError("Release size manifest did not converge")

    checksum_targets = sorted(
        path
        for path in args.output_dir.rglob("*")
        if path.is_file()
        and path != checksum_path
        and path.name not in KAGGLE_CONTROL_FILES
    )
    with checksum_path.open("w", encoding="ascii", newline="\n") as stream:
        for index, path in enumerate(checksum_targets, 1):
            stream.write(f"{_sha256(path)}  {path.relative_to(args.output_dir).as_posix()}\n")
            if index % 5000 == 0:
                print(f"checksums {index}/{len(checksum_targets)}", flush=True)

    actual_release_bytes = sum(
        path.stat().st_size
        for path in args.output_dir.rglob("*")
        if path.is_file() and path.name not in KAGGLE_CONTROL_FILES
    )
    if actual_release_bytes != manifest["apparent_release_bytes"]:
        raise RuntimeError(
            "Final release byte count differs from manifest: "
            f"actual={actual_release_bytes} manifest={manifest['apparent_release_bytes']}"
        )

    _write_kaggle_metadata(
        args.output_dir / "dataset-metadata.json",
        description=kaggle_description,
        metadata_path=args.metadata,
        release_root=args.output_dir,
    )

    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
