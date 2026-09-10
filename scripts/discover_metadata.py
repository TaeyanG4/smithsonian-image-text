#!/usr/bin/env python3
"""Build a small or full metadata-only Smithsonian CC0 image candidate pool."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smithsonian_image_text.discovery import build_session, discover_candidates  # noqa: E402


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_provenance() -> dict[str, object]:
    def run(*args: str) -> str | None:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
        )
        return result.stdout.strip() if result.returncode == 0 else None

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    return {"git_commit": commit, "git_dirty": bool(status) if status is not None else None}


def _partial_path(path: Path) -> Path:
    return path.with_name(path.name + ".partial")


def _write_json_atomic(path: Path, payload: dict) -> None:
    partial = _partial_path(path)
    partial.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(partial, path)


def _validate_distinct_paths(paths: list[Path]) -> None:
    resolved = [path.resolve() for path in paths]
    if len(resolved) != len(set(resolved)):
        raise SystemExit("Output, report, raw-record, and source-manifest paths must be distinct")


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
    units_group = parser.add_mutually_exclusive_group()
    units_group.add_argument("--units", nargs="+", help="Explicit unit codes to scan.")
    units_group.add_argument(
        "--all-preferred-units",
        action="store_true",
        help="Use every configured preferred unit. Intended for an explicit Phase 2 run.",
    )
    parser.add_argument("--max-per-unit", type=int, default=None)
    parser.add_argument("--max-shards-per-unit", type=int, default=None)
    parser.add_argument(
        "--shard-offset",
        type=int,
        default=0,
        help="Skip this many deterministic shards per unit before scanning; useful for Phase 2 extensions.",
    )
    parser.add_argument(
        "--raw-records-output",
        type=Path,
        default=None,
        help=(
            "Optional gzip NDJSON path for raw Smithsonian records that produced at least one "
            "CC0 image candidate. Still metadata-only."
        ),
    )
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
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=None,
        help="Optional source snapshot manifest path; defaults next to --report.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Allow replacement of existing final output files."
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
    min_candidates = int(discovery["min_candidates"])
    max_candidates = int(discovery["max_candidates"])
    if args.target <= 0:
        raise SystemExit("--target must be positive")
    if args.target > max_candidates:
        raise SystemExit(f"--target may not exceed configured max_candidates={max_candidates}")
    if args.units:
        units = args.units
    elif args.all_preferred_units:
        units = discovery["preferred_units"]
    else:
        units = discovery["smoke_units"]
    max_per_unit = (
        args.max_per_unit
        if args.max_per_unit is not None
        else int(discovery["max_candidates_per_unit"])
    )
    max_shards = (
        args.max_shards_per_unit
        if args.max_shards_per_unit is not None
        else int(discovery["max_shards_per_unit"])
    )
    if max_per_unit <= 0:
        raise SystemExit("--max-per-unit must be positive")
    if max_shards <= 0:
        raise SystemExit("--max-shards-per-unit must be positive")
    if args.shard_offset < 0:
        raise SystemExit("--shard-offset must be zero or positive")
    unit_caps = {
        str(unit).upper(): int(value)
        for unit, value in (discovery.get("unit_candidate_caps") or {}).items()
    }

    if args.target >= min_candidates and args.output.name == "discovery_smoke.ndjson.gz":
        raise SystemExit("Phase 2 scale runs require an explicit --output path, not the smoke default")
    if args.target >= min_candidates and args.report.name == "discovery_smoke_report.json":
        raise SystemExit("Phase 2 scale runs require an explicit --report path, not the smoke default")

    source_manifest_path = args.source_manifest or args.report.with_name(
        args.report.stem + "_source_manifest.json"
    )
    finals = [args.output, args.report, source_manifest_path]
    if args.raw_records_output is not None:
        finals.append(args.raw_records_output)
    _validate_distinct_paths(finals)
    existing = [path for path in finals if path.exists()]
    if existing and not args.force:
        names = ", ".join(str(path) for path in existing)
        raise SystemExit(f"Refusing to overwrite existing output(s) without --force: {names}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    source_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    output_partial = _partial_path(args.output)
    output_partial.unlink(missing_ok=True)
    raw_partial = _partial_path(args.raw_records_output) if args.raw_records_output else None
    if raw_partial is not None:
        raw_partial.unlink(missing_ok=True)
    raw_stream = None
    raw_records_written = 0
    if args.raw_records_output is not None:
        args.raw_records_output.parent.mkdir(parents=True, exist_ok=True)
        raw_stream = gzip.open(raw_partial, "wt", encoding="utf-8", newline="\n")

    def preserve_raw_record(unit: str, shard_url: str, record: dict) -> None:
        nonlocal raw_records_written
        if raw_stream is None:
            return
        payload = {"source_unit": unit, "source_shard_url": shard_url, "record": record}
        raw_stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        raw_records_written += 1

    http = build_session()
    run_error: Exception | None = None
    stats = None
    try:
        rows, stats = discover_candidates(
            units=units,
            target=args.target,
            max_per_unit=max_per_unit,
            unit_candidate_caps=unit_caps,
            max_shards_per_unit=max_shards,
            shard_offset=args.shard_offset,
            seed=str(discovery["deterministic_seed"]),
            max_side=int(project["max_side_px"]),
            timeout=float(discovery["request_timeout_seconds"]),
            index_url=str(sources["bulk_index_url"]),
            session=http,
            candidate_record_callback=preserve_raw_record if raw_stream is not None else None,
        )

        with gzip.open(output_partial, "wt", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception as exc:
        run_error = exc
    finally:
        if raw_stream is not None:
            raw_stream.close()
        http.close()

    if run_error is not None:
        failure = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "metadata_only",
            "complete": False,
            "error_type": type(run_error).__name__,
            "error": str(run_error),
            "partial_output": str(output_partial) if output_partial.exists() else None,
            "partial_raw_records": str(raw_partial) if raw_partial and raw_partial.exists() else None,
        }
        _write_json_atomic(args.report, failure)
        raise run_error

    assert stats is not None
    phase2_scale = args.target >= min_candidates
    target_met = stats.candidates_emitted >= args.target
    minimum_met = stats.candidates_emitted >= min_candidates if phase2_scale else None
    complete = not phase2_scale or bool(minimum_met)

    stats_payload = stats.as_dict()
    source_indexes = stats_payload.pop("source_index_manifest")
    shard_manifest = stats_payload.pop("shard_manifest")
    source_manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bulk_index_url": sources["bulk_index_url"],
        "source_indexes": source_indexes,
        "shards": shard_manifest,
        "candidate_output_partial_sha256": _sha256_file(output_partial),
        "raw_records_partial_sha256": _sha256_file(raw_partial) if raw_partial and raw_partial.exists() else None,
        "config_sha256": _sha256_file(args.config),
        **_git_provenance(),
    }
    source_manifest_partial = _partial_path(source_manifest_path)
    source_manifest_partial.write_text(
        json.dumps(source_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "metadata_only",
        "complete": complete,
        "image_downloads_started": False,
        "bulk_index_url": sources["bulk_index_url"],
        "deterministic_seed": discovery["deterministic_seed"],
        "config": str(args.config),
        "target": args.target,
        "units": stats.normalized_units,
        "unit_candidate_caps": stats.effective_unit_caps,
        "shard_offset": args.shard_offset,
        "max_shards_per_unit": max_shards,
        "output": str(args.output),
        "raw_records_output": str(args.raw_records_output) if args.raw_records_output else None,
        "raw_records_written": raw_records_written,
        "target_met": target_met,
        "configured_minimum_candidates": min_candidates if phase2_scale else None,
        "configured_minimum_met": minimum_met,
        "source_manifest": str(source_manifest_path),
        **stats_payload,
    }
    if complete:
        report["output_sha256"] = _sha256_file(output_partial)
        report["raw_records_sha256"] = (
            _sha256_file(raw_partial) if raw_partial is not None else None
        )
        report_partial = _partial_path(args.report)
        report_partial.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        promoted: list[tuple[Path, Path]] = []
        pairs = [(output_partial, args.output)]
        if raw_partial is not None and args.raw_records_output is not None:
            pairs.append((raw_partial, args.raw_records_output))
        pairs.append((source_manifest_partial, source_manifest_path))
        try:
            for partial, final in pairs:
                os.replace(partial, final)
                promoted.append((partial, final))
            os.replace(report_partial, args.report)
        except Exception:
            for partial, final in reversed(promoted):
                if final.exists() and not partial.exists():
                    os.replace(final, partial)
            raise
    else:
        report["partial_output"] = str(output_partial)
        report["partial_raw_records"] = str(raw_partial) if raw_partial else None
        os.replace(source_manifest_partial, source_manifest_path)
        _write_json_atomic(args.report, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if phase2_scale and not minimum_met:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
