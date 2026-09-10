#!/usr/bin/env python3
"""Build a small or full metadata-only Smithsonian CC0 image candidate pool."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smithsonian_image_text.discovery import discover_candidates  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream official Smithsonian bulk metadata; does not download images."
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "collection.yaml")
    parser.add_argument(
        "--target",
        type=int,
        default=250,
        help="Candidate media rows to emit. Default is deliberately small/safe.",
    )
    parser.add_argument("--units", nargs="+", help="Explicit unit codes to scan.")
    parser.add_argument(
        "--all-preferred-units",
        action="store_true",
        help="Use every configured preferred unit. Intended for an explicit Phase 2 run.",
    )
    parser.add_argument("--max-per-unit", type=int, default=None)
    parser.add_argument("--max-shards-per-unit", type=int, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "interim" / "discovery_smoke.ndjson.gz",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "data" / "audits" / "discovery_smoke_report.json",
    )
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    discovery = config["metadata_discovery"]
    project = config["project"]
    sources = config["sources"]
    if args.units:
        units = args.units
    elif args.all_preferred_units:
        units = discovery["preferred_units"]
    else:
        units = discovery["smoke_units"]
    max_per_unit = args.max_per_unit or int(discovery["max_candidates_per_unit"])
    max_shards = args.max_shards_per_unit or int(discovery["max_shards_per_unit"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)

    rows, stats = discover_candidates(
        units=units,
        target=args.target,
        max_per_unit=max_per_unit,
        max_shards_per_unit=max_shards,
        seed=str(discovery["deterministic_seed"]),
        max_side=int(project["max_side_px"]),
        timeout=float(discovery["request_timeout_seconds"]),
        index_url=str(sources["bulk_index_url"]),
    )

    with gzip.open(args.output, "wt", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "metadata_only",
        "image_downloads_started": False,
        "bulk_index_url": sources["bulk_index_url"],
        "deterministic_seed": discovery["deterministic_seed"],
        "config": str(args.config),
        "target": args.target,
        "units": units,
        "output": str(args.output),
        **stats.as_dict(),
    }
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
