#!/usr/bin/env python3
"""Small source/API probe for Phase 1. Never downloads collection images."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smithsonian_image_text.discovery import BULK_INDEX_URL, fetch_shard_urls, fetch_unit_index_urls  # noqa: E402


API_BASE = "https://api.si.edu/openaccess/api/v1.0"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", default=os.getenv("SMITHSONIAN_API_KEY"))
    parser.add_argument("--units", nargs="*", default=["NMAH", "NASM", "CHNDM", "NMNHPALEO"])
    parser.add_argument(
        "--skip-search",
        action="store_true",
        help="Probe /stats but skip the extra one-row API search request.",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "audits" / "source_probe.json")
    args = parser.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = "smithsonian-image-text/0.1 source-probe"
    unit_indexes = fetch_unit_index_urls(session, BULK_INDEX_URL)
    bulk_head = session.head(BULK_INDEX_URL, timeout=30)
    bulk_head.raise_for_status()
    result: dict[str, object] = {
        "probed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bulk_index_url": BULK_INDEX_URL,
        "bulk_unit_count": len(unit_indexes),
        "bulk_units": sorted(unit_indexes),
        "bulk_index_last_modified": bulk_head.headers.get("Last-Modified"),
        "bulk_index_etag": bulk_head.headers.get("ETag"),
        "units": {},
        "api_probed": False,
    }
    for unit in args.units:
        unit = unit.upper()
        if unit not in unit_indexes:
            result["units"][unit] = {"present": False}  # type: ignore[index]
            continue
        shards = fetch_shard_urls(session, unit_indexes[unit])
        result["units"][unit] = {  # type: ignore[index]
            "present": True,
            "index_url": unit_indexes[unit],
            "shard_count": len(shards),
            "first_shard": shards[0] if shards else None,
        }

    if args.api_key:
        result["api_probed"] = True
        api_result: dict[str, object] = {
            "base": API_BASE,
            "eligibility_truth": "raw record metadata_usage + individual media usage, not /stats",
        }
        stats = session.get(f"{API_BASE}/stats", params={"api_key": args.api_key}, timeout=30)
        api_result["stats_http_status"] = stats.status_code
        if stats.ok:
            stats_json = stats.json()["response"]
            selected_unit_stats = {
                row.get("unit"): row
                for row in stats_json.get("units") or []
                if row.get("unit") in {unit.upper() for unit in args.units}
            }
            metric_anomalies = []
            for row in stats_json.get("units") or []:
                metrics = row.get("metrics") or {}
                cc0_records = metrics.get("CC0_records")
                records_with_media = metrics.get("CC0_records_with_CC0_media")
                if isinstance(cc0_records, int) and isinstance(records_with_media, int):
                    if records_with_media > cc0_records:
                        metric_anomalies.append(
                            {
                                "unit": row.get("unit"),
                                "CC0_records": cc0_records,
                                "CC0_records_with_CC0_media": records_with_media,
                            }
                        )
            api_result.update(
                {
                    "stats_time": stats_json.get("time"),
                    "stats_total_objects": stats_json.get("total_objects"),
                    "stats_metrics": stats_json.get("metrics"),
                    "selected_unit_stats": selected_unit_stats,
                    "metric_anomalies": metric_anomalies,
                }
            )
        else:
            api_result["stats_error"] = f"HTTP {stats.status_code}"

        if not args.skip_search:
            query = 'online_media_type:"Images" AND media_usage:"CC0"'
            search = session.get(
                f"{API_BASE}/search",
                params={
                    "q": query,
                    "start": 0,
                    "rows": 1,
                    "sort": "id",
                    "type": "edanmdm",
                    "row_group": "objects",
                    "api_key": args.api_key,
                },
                timeout=30,
            )
            api_result["search_http_status"] = search.status_code
            api_result["cc0_image_query"] = query
            if search.ok:
                search_json = search.json()["response"]
                api_result["cc0_image_query_row_count"] = search_json.get("rowCount")
                api_result["sample_unit"] = (search_json.get("rows") or [{}])[0].get("unitCode")
            else:
                api_result["search_error"] = f"HTTP {search.status_code}"
        result["api"] = api_result

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
