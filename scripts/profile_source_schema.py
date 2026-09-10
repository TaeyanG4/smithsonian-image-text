#!/usr/bin/env python3
"""Profile live Smithsonian bulk EDAN field shapes without downloading image bytes."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smithsonian_image_text.discovery import (  # noqa: E402
    build_session,
    deterministic_shard_order,
    fetch_shard_urls,
    fetch_unit_index_urls,
    iter_ndjson_records,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "collection.yaml")
    parser.add_argument("--units", nargs="+", help="Explicit unit codes. Defaults to smoke_units.")
    parser.add_argument("--shards-per-unit", type=int, default=1)
    parser.add_argument("--max-records", type=int, default=20_000)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "audits" / "source_schema_profile.json",
    )
    return parser.parse_args()


def _inc_keys(counter: Counter[str], value: object) -> None:
    if isinstance(value, dict):
        counter.update(str(key) for key in value)


def _top(counter: Counter[str], n: int = 100) -> dict[str, int]:
    return dict(counter.most_common(n))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.shards_per_unit <= 0:
        raise SystemExit("--shards-per-unit must be positive")
    if args.max_records <= 0:
        raise SystemExit("--max-records must be positive")

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    discovery = config["metadata_discovery"]
    index_url = str(config["sources"]["bulk_index_url"])
    units = [str(unit).upper() for unit in (args.units or discovery["smoke_units"])]
    seed = str(discovery["deterministic_seed"])
    timeout = float(discovery["request_timeout_seconds"])

    counters: dict[str, Counter[str]] = {
        "top_level_keys": Counter(),
        "content_keys": Counter(),
        "freetext_groups": Counter(),
        "indexed_structured_keys": Counter(),
        "descriptive_non_repeating_keys": Counter(),
        "media_keys": Counter(),
        "media_resource_labels": Counter(),
        "media_types": Counter(),
        "metadata_usage_access": Counter(),
        "media_usage_access": Counter(),
        "media_hosts": Counter(),
    }
    freetext_labels: dict[str, Counter[str]] = defaultdict(Counter)
    per_unit_records: Counter[str] = Counter()
    records_with_media = 0
    media_items = 0
    image_media_items = 0
    records_seen = 0
    shard_urls_read: list[str] = []

    session = build_session()
    try:
        unit_indexes = fetch_unit_index_urls(session, index_url=index_url, timeout=timeout)
        for unit in units:
            if records_seen >= args.max_records:
                break
            if unit not in unit_indexes:
                continue
            shards = deterministic_shard_order(
                fetch_shard_urls(session, unit_indexes[unit], timeout=timeout),
                seed=seed,
                unit_code=unit,
            )[: args.shards_per_unit]
            for shard_url in shards:
                if records_seen >= args.max_records:
                    break
                shard_urls_read.append(shard_url)
                for record in iter_ndjson_records(session, shard_url, timeout=timeout):
                    if records_seen >= args.max_records:
                        break
                    records_seen += 1
                    per_unit_records[unit] += 1
                    _inc_keys(counters["top_level_keys"], record)

                    content = record.get("content") or {}
                    _inc_keys(counters["content_keys"], content)
                    freetext = content.get("freetext") or {}
                    _inc_keys(counters["freetext_groups"], freetext)
                    for group, values in freetext.items() if isinstance(freetext, dict) else []:
                        if not isinstance(values, list):
                            continue
                        for item in values:
                            if isinstance(item, dict) and item.get("label"):
                                freetext_labels[str(group)].update([str(item["label"])])

                    indexed = content.get("indexedStructured") or {}
                    _inc_keys(counters["indexed_structured_keys"], indexed)
                    dnr = content.get("descriptiveNonRepeating") or {}
                    _inc_keys(counters["descriptive_non_repeating_keys"], dnr)

                    metadata_access = (dnr.get("metadata_usage") or {}).get("access")
                    counters["metadata_usage_access"].update([str(metadata_access or "<missing>")])

                    online = dnr.get("online_media") or {}
                    media = online.get("media") or []
                    if media:
                        records_with_media += 1
                    for item in media:
                        if not isinstance(item, dict):
                            continue
                        media_items += 1
                        _inc_keys(counters["media_keys"], item)
                        media_type = str(item.get("type") or "<missing>")
                        counters["media_types"].update([media_type])
                        if media_type == "Images":
                            image_media_items += 1
                        media_access = (item.get("usage") or {}).get("access")
                        counters["media_usage_access"].update([str(media_access or "<missing>")])
                        host = urlparse(str(item.get("content") or "")).netloc or "<missing>"
                        counters["media_hosts"].update([host])
                        for resource in item.get("resources") or []:
                            if isinstance(resource, dict):
                                counters["media_resource_labels"].update(
                                    [str(resource.get("label") or "<missing>")]
                                )
    finally:
        session.close()

    interesting_labels = {}
    needles = ("right", "restrict", "sensitive", "culture", "repatri", "sacred", "burial")
    for group, labels in freetext_labels.items():
        matches = {
            label: count
            for label, count in labels.items()
            if any(needle in label.casefold() for needle in needles)
        }
        if matches:
            interesting_labels[group] = dict(sorted(matches.items()))

    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "metadata_only",
        "image_bytes_read": 0,
        "bulk_index_url": index_url,
        "deterministic_seed": seed,
        "units_requested": units,
        "records_seen": records_seen,
        "per_unit_records": dict(per_unit_records),
        "records_with_media": records_with_media,
        "media_items": media_items,
        "image_media_items": image_media_items,
        "shard_urls_read": shard_urls_read,
        **{name: _top(counter) for name, counter in counters.items()},
        "freetext_labels_top": {
            group: _top(labels, 30) for group, labels in sorted(freetext_labels.items())
        },
        "potential_review_related_freetext_labels": interesting_labels,
        "note": (
            "Observed keys/labels are schema evidence, not a guarantee of universality. "
            "Absence of a sensitive-related key or label is not a safety determination."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
