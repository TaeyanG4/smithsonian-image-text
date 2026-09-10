#!/usr/bin/env python3
"""Materialize Phase 2/3 Parquet tables from metadata-only discovery output."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from collections import Counter
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smithsonian_image_text.filtering import evaluate_candidate  # noqa: E402


STRING_FIELDS = [
    "object_id",
    "edan_id",
    "media_id",
    "ids_id",
    "unit_code",
    "title",
    "description",
    "object_type",
    "institution",
    "collection",
    "creator",
    "related_names",
    "date",
    "place",
    "topics",
    "culture",
    "scientific_name",
    "physical_description",
    "credit_line",
    "usage_flags",
    "source_url",
    "record_guid",
    "media_guid",
    "media_url",
    "image_url",
    "thumbnail_url",
    "media_type",
    "media_rights",
    "metadata_rights",
    "object_rights",
    "indexed_media_rights",
    "media_caption",
    "alt_text",
    "media_description",
    "record_type",
    "record_hash",
    "raw_category",
    "highres_jpeg_url",
    "screen_url",
    "thumbnail_resource_url",
    "source_shard_url",
    "eligibility_status",
    "eligibility_reasons",
]

INT_FIELDS = ["record_timestamp", "record_last_updated", "source_width", "source_height"]

SCHEMA = pa.schema(
    [*(pa.field(name, pa.string()) for name in STRING_FIELDS), *(pa.field(name, pa.int64()) for name in INT_FIELDS)]
)


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _normalized_row(row: dict, status: str, reasons: tuple[str, ...]) -> dict:
    out = {field: row.get(field) for field in STRING_FIELDS + INT_FIELDS}
    out["eligibility_status"] = status
    out["eligibility_reasons"] = "|".join(reasons) if reasons else None
    for field in STRING_FIELDS:
        value = out.get(field)
        if value is not None and not isinstance(value, str):
            out[field] = str(value)
    for field in INT_FIELDS:
        value = out.get(field)
        if value is None or value == "":
            out[field] = None
        else:
            try:
                out[field] = int(value)
            except (TypeError, ValueError):
                out[field] = None
    return out


def _scan_shared_media(input_path: Path) -> tuple[set[str], dict[str, dict[str, object]]]:
    """Find exact media URLs attached to more than one object before eligibility output."""
    objects_by_url: dict[str, set[str]] = defaultdict(set)
    rows_by_url: Counter[str] = Counter()
    units_by_url: dict[str, set[str]] = defaultdict(set)
    with _open_text(input_path) as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            media_url = str(row.get("media_url") or "").strip()
            object_id = str(row.get("object_id") or "").strip()
            if not media_url or not object_id:
                continue
            objects_by_url[media_url].add(object_id)
            rows_by_url[media_url] += 1
            unit = str(row.get("unit_code") or "").strip()
            if unit:
                units_by_url[media_url].add(unit)

    shared = {url for url, object_ids in objects_by_url.items() if len(object_ids) > 1}
    details = {
        url: {
            "media_url": url,
            "row_count": rows_by_url[url],
            "object_count": len(objects_by_url[url]),
            "object_ids": sorted(objects_by_url[url]),
            "unit_codes": sorted(units_by_url[url]),
        }
        for url in shared
    }
    return shared, details


class WriterSet:
    def __init__(self, output_dir: Path):
        self.paths = {
            "all": output_dir / "candidates.parquet",
            "eligible": output_dir / "eligible_candidates.parquet",
            "rejected": output_dir / "rejected_candidates.parquet",
            "review_required": output_dir / "review_candidates.parquet",
        }
        self.writers: dict[str, pq.ParquetWriter] = {}

    def write(self, key: str, rows: list[dict]) -> None:
        if not rows:
            return
        table = pa.Table.from_pylist(rows, schema=SCHEMA)
        writer = self.writers.get(key)
        if writer is None:
            writer = pq.ParquetWriter(self.paths[key], SCHEMA, compression="zstd")
            self.writers[key] = writer
        writer.write_table(table)

    def close(self) -> None:
        for writer in self.writers.values():
            writer.close()
        for key, path in self.paths.items():
            if key not in self.writers:
                pq.write_table(pa.Table.from_pylist([], schema=SCHEMA), path, compression="zstd")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=ROOT / "data" / "interim" / "phase2_candidates.ndjson.gz",
    )
    parser.add_argument(
        "--rules", type=Path, default=ROOT / "config" / "eligibility_rules.yaml"
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "interim")
    parser.add_argument(
        "--audit-dir", type=Path, default=ROOT / "data" / "audits"
    )
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()

    rules = yaml.safe_load(args.rules.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.audit_dir.mkdir(parents=True, exist_ok=True)

    writers = WriterSet(args.output_dir)
    shared_media_urls, shared_media_details = _scan_shared_media(args.input)
    batches: dict[str, list[dict]] = {
        "all": [],
        "eligible": [],
        "rejected": [],
        "review_required": [],
    }
    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    unit_counts: Counter[str] = Counter()
    institution_counts: Counter[str] = Counter()
    object_counts: Counter[str] = Counter()
    object_type_counts: Counter[str] = Counter()
    media_host_counts: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    total = 0
    seen_object_media: set[tuple[str, str]] = set()
    profile_fields = [
        "title",
        "description",
        "object_type",
        "creator",
        "date",
        "place",
        "topics",
        "scientific_name",
        "media_caption",
    ]

    review_csv_path = args.audit_dir / "manual_review.csv"
    with review_csv_path.open("w", encoding="utf-8-sig", newline="") as review_stream:
        review_writer = csv.DictWriter(
            review_stream,
            fieldnames=[
                "object_id",
                "media_id",
                "unit_code",
                "title",
                "object_type",
                "topics",
                "culture",
                "source_url",
                "eligibility_reasons",
            ],
        )
        review_writer.writeheader()

        with _open_text(args.input) as stream:
            for line in stream:
                if not line.strip():
                    continue
                source = json.loads(line)
                decision = evaluate_candidate(source, rules)
                structural_reasons: list[str] = []
                media_url_value = str(source.get("media_url") or "").strip()
                object_id_value = str(source.get("object_id") or "").strip()
                pair = (object_id_value, media_url_value)
                if media_url_value in shared_media_urls:
                    structural_reasons.append("SHARED_MEDIA_ACROSS_OBJECTS")
                if pair in seen_object_media:
                    structural_reasons.append("DUPLICATE_OBJECT_MEDIA")
                else:
                    seen_object_media.add(pair)

                if structural_reasons:
                    status = "rejected"
                    reasons = tuple(dict.fromkeys((*decision.reasons, *structural_reasons)))
                else:
                    status = decision.status
                    reasons = decision.reasons
                row = _normalized_row(source, status, reasons)
                total += 1
                status_counts[status] += 1
                reason_counts.update(reasons)
                unit_counts[str(row.get("unit_code") or "")] += 1
                institution_counts[str(row.get("institution") or "")] += 1
                object_counts[str(row.get("object_id") or "")] += 1
                host = ""
                media_url = str(row.get("media_url") or "")
                if "://" in media_url:
                    host = media_url.split("/", 3)[2].casefold()
                media_host_counts[host] += 1
                for field in profile_fields:
                    if not row.get(field):
                        missing[field] += 1
                for token in str(row.get("object_type") or "").split(";"):
                    token = token.strip()
                    if token:
                        object_type_counts[token] += 1

                batches["all"].append(row)
                batches[status].append(row)
                if status == "review_required":
                    review_writer.writerow(
                        {
                            key: row.get(key)
                            for key in review_writer.fieldnames
                        }
                    )

                if len(batches["all"]) >= args.batch_size:
                    for key, batch in batches.items():
                        writers.write(key, batch)
                        batch.clear()

    for key, batch in batches.items():
        writers.write(key, batch)
    writers.close()

    shared_media_path = args.audit_dir / "shared_media_across_objects.csv"
    with shared_media_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["media_url", "row_count", "object_count", "unit_codes", "object_ids"],
        )
        writer.writeheader()
        for detail in sorted(
            shared_media_details.values(),
            key=lambda item: (-int(item["object_count"]), str(item["media_url"])),
        ):
            writer.writerow(
                {
                    "media_url": detail["media_url"],
                    "row_count": detail["row_count"],
                    "object_count": detail["object_count"],
                    "unit_codes": "|".join(detail["unit_codes"]),
                    "object_ids": "|".join(detail["object_ids"]),
                }
            )

    multi_view_objects = sum(1 for count in object_counts.values() if count > 1)
    max_views = max(object_counts.values(), default=0)
    usable = status_counts["eligible"] + status_counts["review_required"]
    report = {
        "input": str(args.input),
        "rows": total,
        "unique_objects": len(object_counts),
        "objects_with_multiple_media_rows": multi_view_objects,
        "max_media_rows_for_one_object": max_views,
        "eligibility_status": dict(status_counts),
        "eligibility_reasons": dict(reason_counts),
        "shared_media_groups": len(shared_media_urls),
        "shared_media_audit_csv": str(shared_media_path),
        "usable_text_ratio_after_basic_gate": round(usable / total, 4) if total else 0.0,
        "unit_distribution": dict(unit_counts),
        "institution_distribution": dict(institution_counts),
        "media_hosts": dict(media_host_counts),
        "missing_ratio": {
            field: round(missing[field] / total, 4) if total else 0.0 for field in profile_fields
        },
        "top_object_types": dict(object_type_counts.most_common(100)),
        "outputs": {key: str(path) for key, path in writers.paths.items()},
        "manual_review_csv": str(review_csv_path),
        "image_bytes_read": 0,
    }
    report_path = args.audit_dir / "discovery_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
