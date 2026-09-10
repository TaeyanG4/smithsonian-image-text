#!/usr/bin/env python3
"""Profile a metadata-only candidate NDJSON(.gz) file without touching image bytes."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smithsonian_image_text.filtering import evaluate_candidate  # noqa: E402


PROFILE_FIELDS = [
    "title",
    "description",
    "media_caption",
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
    "source_url",
    "media_url",
    "image_url",
    "alt_text",
    "media_description",
]


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=ROOT / "data" / "interim" / "discovery_smoke.ndjson.gz",
    )
    parser.add_argument(
        "--rules", type=Path, default=ROOT / "config" / "eligibility_rules.yaml"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data" / "audits" / "candidate_profile.json"
    )
    args = parser.parse_args()

    rules = yaml.safe_load(args.rules.read_text(encoding="utf-8"))
    rows = 0
    unit_counts: Counter[str] = Counter()
    object_counts: Counter[str] = Counter()
    metadata_rights: Counter[str] = Counter()
    media_rights: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    media_hosts: Counter[str] = Counter()
    review_samples: list[dict[str, object]] = []
    non_ids_samples: list[dict[str, object]] = []

    with _open_text(args.input) as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            unit_counts[str(row.get("unit_code") or "")] += 1
            object_counts[str(row.get("object_id") or "")] += 1
            metadata_rights[str(row.get("metadata_rights") or "")] += 1
            media_rights[str(row.get("media_rights") or "")] += 1
            media_host = urlparse(str(row.get("media_url") or "")).netloc
            media_hosts[media_host] += 1
            if media_host and media_host.casefold() != "ids.si.edu" and len(non_ids_samples) < 10:
                non_ids_samples.append(
                    {
                        "unit_code": row.get("unit_code"),
                        "object_id": row.get("object_id"),
                        "media_url": row.get("media_url"),
                        "image_url": row.get("image_url"),
                    }
                )
            for field in PROFILE_FIELDS:
                value = row.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    missing[field] += 1

            decision = evaluate_candidate(row, rules)
            status_counts[decision.status] += 1
            reason_counts.update(decision.reasons)
            if decision.status == "review_required" and len(review_samples) < 20:
                review_samples.append(
                    {
                        "unit_code": row.get("unit_code"),
                        "object_id": row.get("object_id"),
                        "title": row.get("title"),
                        "object_type": row.get("object_type"),
                        "topics": row.get("topics"),
                    }
                )

    duplicate_view_objects = sum(1 for count in object_counts.values() if count > 1)
    usable = status_counts["eligible"] + status_counts["review_required"]
    report = {
        "rows": rows,
        "unique_objects": len(object_counts),
        "objects_with_multiple_media_rows": duplicate_view_objects,
        "unit_distribution": dict(unit_counts),
        "metadata_rights": dict(metadata_rights),
        "media_rights": dict(media_rights),
        "eligibility_status": dict(status_counts),
        "eligibility_reasons": dict(reason_counts),
        "usable_after_basic_text_gate_ratio": round(usable / rows, 4) if rows else 0.0,
        "missing_counts": dict(missing),
        "missing_ratio": {
            field: round(missing[field] / rows, 4) if rows else 0.0 for field in PROFILE_FIELDS
        },
        "media_hosts": dict(media_hosts),
        "non_ids_samples": non_ids_samples,
        "review_samples": review_samples,
        "image_bytes_read": 0,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
