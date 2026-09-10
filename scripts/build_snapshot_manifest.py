#!/usr/bin/env python3
"""Hash local Phase 2-4 build artifacts to pin the candidate snapshot used by V1."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ARTIFACTS = [
    "data/raw_metadata/phase2_candidate_records.ndjson.gz",
    "data/raw_metadata/phase2_candidate_records_extension_32_63.ndjson.gz",
    "data/raw_metadata/phase2_candidate_records_extension_64_127.ndjson.gz",
    "data/interim/phase2_candidates.ndjson.gz",
    "data/interim/phase2_candidates_extension_32_63.ndjson.gz",
    "data/interim/phase2_candidates_extension_64_127.ndjson.gz",
    "data/interim/phase2_candidates_merged.ndjson.gz",
    "data/interim/candidates.parquet",
    "data/interim/eligible_candidates.parquet",
    "data/interim/rejected_candidates.parquet",
    "data/interim/review_candidates.parquet",
    "data/interim/selected_candidates.parquet",
    "data/audits/phase2_discovery_report.json",
    "data/audits/phase2_extension_32_63_report.json",
    "data/audits/phase2_extension_64_127_report.json",
    "data/audits/phase2_merge_report.json",
    "data/audits/discovery_report.json",
    "data/audits/sampling_report.json",
    "config/collection.yaml",
    "config/eligibility_rules.yaml",
    "config/category_mapping.yaml",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git() -> dict[str, object]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return {
        "git_commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "git_dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    output = ROOT / "data" / "audits" / "local_snapshot_manifest.json"
    files: list[dict[str, object]] = []
    missing: list[str] = []
    for relative in ARTIFACTS:
        path = ROOT / relative
        if not path.is_file():
            missing.append(relative)
            continue
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )

    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Pin the exact local metadata/candidate snapshot used for V1 selection.",
        "files": files,
        "missing_expected_files": missing,
        "network_snapshot_note": (
            "The completed large Phase 2 runs predate per-shard ETag/SHA256 capture. "
            "Their reports preserve shard URLs and the raw candidate-producing records are preserved "
            "and hashed here. Future discovery runs capture source index and shard identities directly."
        ),
        **_git(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"files_hashed": len(files), "missing": missing, "output": str(output)}, indent=2))
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
