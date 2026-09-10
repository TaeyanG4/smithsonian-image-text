#!/usr/bin/env python3
"""Build Phase 9 canonical metadata from selected candidates, image manifest, and QA decisions."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smithsonian_image_text.captions import TEXT_SOURCE, build_model_text  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=ROOT / "data" / "interim" / "production_candidates.parquet",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "audits" / "production_manifest.parquet",
    )
    parser.add_argument(
        "--qa-decisions",
        type=Path,
        default=ROOT / "data" / "audits" / "image_qa_decisions.parquet",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "interim" / "metadata_pre_split.parquet",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "data" / "audits" / "metadata_build_report.json",
    )
    args = parser.parse_args()

    candidates = {int(row["image_id"]): row for row in pq.read_table(args.candidates).to_pylist()}
    manifest = {int(row["image_id"]): row for row in pq.read_table(args.manifest).to_pylist()}
    decisions = {int(row["image_id"]): row for row in pq.read_table(args.qa_decisions).to_pylist()}

    output_rows: list[dict] = []
    excluded = Counter()
    for image_id in sorted(candidates):
        candidate = candidates[image_id]
        image = manifest.get(image_id)
        qa = decisions.get(image_id)
        if image is None or image.get("status") != "success":
            excluded["NO_SUCCESSFUL_IMAGE"] += 1
            continue
        if qa is None or qa.get("qa_status") != "keep":
            excluded[str((qa or {}).get("qa_reasons") or "NO_QA_KEEP")] += 1
            continue
        if candidate.get("metadata_rights") != "CC0" or candidate.get("media_rights") != "CC0":
            raise ValueError(f"Non-CC0 row reached final metadata: image_id={image_id}")

        model_text = build_model_text(candidate)
        if not model_text:
            excluded["EMPTY_MODEL_TEXT"] += 1
            continue
        width = int(image["final_width"])
        height = int(image["final_height"])
        output_rows.append(
            {
                "image_id": image_id,
                "object_id": candidate.get("object_id"),
                "media_id": candidate.get("media_id"),
                "file_name": image.get("file_name"),
                "title": candidate.get("title"),
                "description": candidate.get("description"),
                "model_text": model_text,
                "text_source": TEXT_SOURCE,
                "category": candidate.get("category"),
                "category_code": candidate.get("category_code"),
                "object_type": candidate.get("object_type"),
                "institution": candidate.get("institution"),
                "collection": candidate.get("collection"),
                "creator": candidate.get("creator"),
                "related_names": candidate.get("related_names"),
                "date": candidate.get("date"),
                "place": candidate.get("place"),
                "topics": candidate.get("topics"),
                "culture": candidate.get("culture"),
                "scientific_name": candidate.get("scientific_name"),
                "physical_description": candidate.get("physical_description"),
                "credit_line": candidate.get("credit_line"),
                "media_caption": candidate.get("media_caption"),
                "alt_text": candidate.get("alt_text"),
                "media_description": candidate.get("media_description"),
                "width": width,
                "height": height,
                "aspect_ratio": width / height,
                "source_url": candidate.get("source_url"),
                "media_url": candidate.get("media_url"),
                "image_url": candidate.get("image_url"),
                "rights": "CC0",
                "metadata_rights": candidate.get("metadata_rights"),
                "media_rights": candidate.get("media_rights"),
                "object_rights": candidate.get("object_rights"),
                "record_guid": candidate.get("record_guid"),
                "media_guid": candidate.get("media_guid"),
                "unit_code": candidate.get("unit_code"),
                "sha256": image.get("sha256"),
                "phash": image.get("phash"),
                "final_bytes": int(image.get("final_bytes") or 0),
                "qa_flags": qa.get("qa_flags"),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(output_rows), args.output, compression="zstd")
    category_counts = Counter(str(row.get("category_code")) for row in output_rows)
    institution_counts = Counter(str(row.get("institution")) for row in output_rows)
    report = {
        "input_candidates": len(candidates),
        "final_metadata_rows": len(output_rows),
        "unique_objects": len({str(row["object_id"]) for row in output_rows}),
        "excluded": dict(excluded),
        "category_distribution": dict(category_counts),
        "institution_distribution": dict(institution_counts),
        "usable_model_text_ratio": (
            sum(bool(row.get("model_text")) for row in output_rows) / len(output_rows)
            if output_rows
            else 0.0
        ),
        "output": str(args.output),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
