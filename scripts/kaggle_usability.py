#!/usr/bin/env python3
"""Audit and, when authorized, synchronize Kaggle Data Explorer descriptions.

The ordinary Kaggle dataset metadata update persists dataset-level metadata but
does not currently populate the analyzed Data Explorer file/column description
fields used by the Usability score. This tool keeps the repository metadata as
the source of truth, validates the exact live file/column layout for the latest
READY dataset version (or a version selected explicitly), and can submit the
same metadata shape used by Kaggle's web application.

The default mode is read-only. Pass ``--apply`` to attempt the API-token
authenticated Data Explorer write, or ``--browser-script`` to emit a
same-origin JavaScript batch that can be run from an already authenticated
Kaggle dataset page. The generated JavaScript contains no credentials; it uses
the page's own session and anti-forgery cookies at runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests


ROOT = Path(__file__).resolve().parents[1]
METADATA_PATH = ROOT / "data" / "release" / "museum-images" / "dataset-metadata.json"
RELEASE_ROOT = ROOT / "data" / "release"
AUDIT_PATH = ROOT / "tmp_research" / "kaggle_usability_audit.json"
BROWSER_SCRIPT_PATH = ROOT / "tmp_research" / "kaggle_usability_browser_sync.js"

OWNER = "taeyangg4"
DATASET_SLUG = "smithsonian-25k-museum-image-text"
DATASET_REF = f"{OWNER}/{DATASET_SLUG}"
DATASET_ID = 11_974_059

KAGGLE_ORIGIN = "https://www.kaggle.com"
GET_DATASET_BASICS = "/api/i/datasets.DatasetDetailService/GetDatasetBasics"
GET_DATASET_USABILITY = "/api/i/datasets.DatasetDetailService/GetDatasetUsabilityRating"
GET_DATASET_HISTORY = "/api/i/datasets.DatasetService/GetDatasetHistory"
GET_DATABUNDLE_EXTERNAL = "/api/i/datasets.databundles.DatabundleService/GetDatabundleExternal"
GET_DATABUNDLE_EXTERNAL_CHILDREN = (
    "/api/i/datasets.databundles.DatabundleService/GetDatabundleExternalChildren"
)
GET_DATABUNDLE_EXTERNAL_COLUMNS = (
    "/api/i/datasets.databundles.DatabundleService/GetDatabundleExternalColumns"
)
GET_DATABUNDLE_EXTERNAL_COLUMNS_BY_PATH = (
    "/api/i/datasets.databundles.DatabundleService/GetDatabundleExternalColumnsByFirestorePath"
)
UPDATE_DATABUNDLE_METADATA_EXTERNAL = (
    "/api/i/datasets.databundles.DatabundleService/UpdateDatabundleMetadataExternal"
)


class KaggleUsabilityError(RuntimeError):
    """Raised when live Kaggle state does not match the approved release."""


class _Response(Protocol):
    status_code: int
    text: str

    def json(self) -> Any: ...

    def raise_for_status(self) -> None: ...


class _Session(Protocol):
    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        timeout: float,
    ) -> _Response: ...


@dataclass(frozen=True)
class LiveContext:
    dataset_id: int
    dataset_version_id: int
    databundle_version_id: int
    version_number: int
    root_firestore_path: str
    file_firestore_paths: dict[str, str]


def _post_json(
    session: _Session,
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    response = session.post(
        f"{KAGGLE_ORIGIN}{endpoint}",
        json=payload,
        timeout=timeout,
    )
    try:
        response.raise_for_status()
    except Exception as exc:
        body = " ".join((getattr(response, "text", "") or "").split())[:500]
        detail = f": {body}" if body else ""
        raise KaggleUsabilityError(
            f"Kaggle request failed for {endpoint} "
            f"(HTTP {getattr(response, 'status_code', '?')}){detail}"
        ) from exc
    try:
        value = response.json()
    except Exception as exc:
        raise KaggleUsabilityError(f"Kaggle returned non-JSON for {endpoint}") from exc
    if not isinstance(value, dict):
        raise KaggleUsabilityError(f"Unexpected Kaggle response for {endpoint}")
    if int(value.get("code", 0) or 0) >= 400:
        raise KaggleUsabilityError(
            f"Kaggle rejected {endpoint}: {value.get('message', 'unknown error')}"
        )
    return value


def _resources() -> dict[str, dict[str, Any]]:
    raw = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    resources = raw.get("resources") or []
    result: dict[str, dict[str, Any]] = {}
    for item in resources:
        resource = dict(item)
        path = str(resource.get("path") or "")
        if not path:
            raise KaggleUsabilityError("dataset-metadata.json contains a resource without path")
        if path in result:
            raise KaggleUsabilityError(f"duplicate resource path: {path}")
        result[path] = resource
    return result


def _top_level_resource_names(path: Path) -> set[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    resources = raw.get("resources") or []
    return {
        str(item.get("path") or "")
        for item in resources
        if isinstance(item, dict)
        and item.get("path")
        and "/" not in str(item.get("path"))
    }


def select_metadata_path(context: LiveContext, explicit: Path | None = None) -> Path:
    """Select local release metadata whose top-level resources match Kaggle.

    Historical and presentation-only Kaggle versions can intentionally expose
    different Data Explorer roots. Prefer an explicitly supplied metadata file;
    otherwise choose the newest local release metadata whose top-level resource
    set exactly matches the requested live version.
    """

    live_names = set(context.file_firestore_paths)
    if explicit is not None:
        candidate = explicit if explicit.is_absolute() else ROOT / explicit
        candidate = candidate.resolve()
        if not candidate.is_file():
            raise KaggleUsabilityError(f"dataset metadata file not found: {candidate}")
        return candidate

    candidates = [
        path
        for path in RELEASE_ROOT.glob("museum-images*/dataset-metadata.json")
        if path.is_file()
    ]
    matching = [path for path in candidates if _top_level_resource_names(path) == live_names]
    if not matching:
        raise KaggleUsabilityError(
            "no local dataset-metadata.json matches the live Kaggle root files: "
            f"{sorted(live_names)}"
        )
    return max(matching, key=lambda path: path.stat().st_mtime_ns)


def _live_resources(context: LiveContext) -> dict[str, dict[str, Any]]:
    """Return local metadata for files Kaggle exposes at the Data Explorer root.

    Release metadata can legitimately describe files inside upload directories
    (for example ``starter_5k/metadata.parquet``). Kaggle uploads those
    directories as archives, while its Data Explorer root exposes only the
    analyzed top-level resources used by the Usability checklist. Keep the
    nested metadata, but audit only files that actually exist in this live
    Data Explorer version.
    """
    resources = _resources()
    live_names = set(context.file_firestore_paths)
    missing = live_names - set(resources)
    if missing:
        raise KaggleUsabilityError(
            f"dataset-metadata.json is missing live Kaggle files: {sorted(missing)}"
        )

    missing_top_level = {
        name for name in resources if "/" not in name and name not in live_names
    }
    if missing_top_level:
        raise KaggleUsabilityError(
            "dataset-metadata.json contains top-level resources absent from live Kaggle: "
            f"{sorted(missing_top_level)}"
        )
    return {name: resources[name] for name in context.file_firestore_paths}


def _verification(context: LiveContext) -> dict[str, int]:
    return {
        "databundleVersionId": context.databundle_version_id,
        "datasetId": context.dataset_id,
    }


def latest_ready_version(session: _Session) -> int:
    history = _post_json(
        session,
        GET_DATASET_HISTORY,
        {"datasetId": DATASET_ID, "count": 100},
    )
    items = history.get("items")
    if not isinstance(items, list):
        raise KaggleUsabilityError("Kaggle dataset history is unavailable")
    versions: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        info = item.get("versionInfo")
        if not isinstance(info, dict) or str(info.get("status") or "") != "READY":
            continue
        number = int(info.get("versionNumber", 0) or 0)
        if number > 0:
            versions.append(number)
    if not versions:
        raise KaggleUsabilityError("Kaggle has no READY dataset version")
    latest = max(versions)

    # Kaggle's public history/read model can lag immediately after publication.
    # Probe the next consecutive versions through the Data Explorer APIs so a
    # newly READY version is not missed just because GetDatasetHistory is stale.
    for candidate in range(latest + 1, latest + 11):
        try:
            load_live_context(session, version_number=candidate)
        except KaggleUsabilityError:
            break
        latest = candidate
    return latest


def load_live_context(session: _Session, *, version_number: int) -> LiveContext:
    requested_version = version_number
    basics = _post_json(
        session,
        GET_DATASET_BASICS,
        {
            "ownerSlug": OWNER,
            "datasetSlug": DATASET_SLUG,
            "datasetVersionNumber": requested_version,
        },
    )
    dataset_id = int(basics.get("datasetId", 0) or 0)
    version_number = int(basics.get("datasetVersionNumber", 0) or 0)
    dataset_version_id = int(basics.get("datasetVersionId", 0) or 0)
    data = basics.get("data")
    databundle_version_id = int(data.get("versionId", 0) or 0) if isinstance(data, dict) else 0
    if dataset_id != DATASET_ID:
        raise KaggleUsabilityError(
            f"dataset id changed: expected {DATASET_ID}, got {dataset_id}"
        )
    if version_number != requested_version:
        raise KaggleUsabilityError(
            "Kaggle returned a different dataset version than requested: "
            f"expected {requested_version}, got {version_number}"
        )
    if dataset_version_id <= 0 or databundle_version_id <= 0:
        raise KaggleUsabilityError("Kaggle version identifiers are incomplete")

    provisional = LiveContext(
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        databundle_version_id=databundle_version_id,
        version_number=version_number,
        root_firestore_path="",
        file_firestore_paths={},
    )
    external = _post_json(
        session,
        GET_DATABUNDLE_EXTERNAL,
        {"verificationInfo": _verification(provisional)},
    )
    source = external.get("dataSource")
    if not isinstance(source, dict):
        raise KaggleUsabilityError("Kaggle Data Explorer returned no data source")
    if int(source.get("sourceId", 0) or 0) != DATASET_ID:
        raise KaggleUsabilityError("Data Explorer dataset id changed")
    if int(source.get("versionNumber", 0) or 0) != version_number:
        raise KaggleUsabilityError("Data Explorer version disagrees with the requested version")
    root_path = str(source.get("path") or "")
    version = source.get("databundleVersion")
    if not root_path or not isinstance(version, dict):
        raise KaggleUsabilityError("Data Explorer version tree is incomplete")
    if int(version.get("legacyEntityId", 0) or 0) != databundle_version_id:
        raise KaggleUsabilityError("Data Explorer databundle version id changed")
    version_info = version.get("datasetVersionInfo")
    if (
        not isinstance(version_info, dict)
        or int(version_info.get("datasetVersionId", 0) or 0) != dataset_version_id
    ):
        raise KaggleUsabilityError("Data Explorer dataset version id changed")

    # GetDatabundleExternalChildren is the authoritative view for file
    # descriptions; the nested version tree can omit descriptions.
    children = _post_json(
        session,
        GET_DATABUNDLE_EXTERNAL_CHILDREN,
        {
            "verificationInfo": _verification(provisional),
            "firestorePath": root_path,
            "offset": 0,
            "count": 100,
            "depth": 1,
        },
    )
    files = children.get("files")
    if not isinstance(files, list):
        raise KaggleUsabilityError("Data Explorer file listing is unavailable")
    file_paths = {
        str(item.get("name") or ""): str(item.get("path") or item.get("firestorePath") or "")
        for item in files
        if isinstance(item, dict) and item.get("name")
    }
    if any(not value for value in file_paths.values()):
        raise KaggleUsabilityError("Data Explorer returned a file without Firestore path")
    return LiveContext(
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        databundle_version_id=databundle_version_id,
        version_number=version_number,
        root_firestore_path=root_path,
        file_firestore_paths=file_paths,
    )


def _live_columns(
    session: _Session,
    context: LiveContext,
    *,
    file_path: str,
) -> list[dict[str, Any]]:
    verification = _verification(context)
    base = _post_json(
        session,
        GET_DATABUNDLE_EXTERNAL_COLUMNS,
        {"verificationInfo": verification, "firestorePath": file_path},
    )
    columns = base.get("columns") or []
    if not isinstance(columns, list):
        raise KaggleUsabilityError("Kaggle column listing is unavailable")
    if not columns:
        return []
    ordered = sorted(
        (item for item in columns if isinstance(item, dict)),
        key=lambda item: int(item.get("order", 0) or 0),
    )
    paths = [str(item.get("firestorePath") or item.get("path") or "") for item in ordered]
    if any(not path for path in paths) or len(paths) != len(set(paths)):
        raise KaggleUsabilityError("Kaggle returned invalid column Firestore paths")
    hydrated = _post_json(
        session,
        GET_DATABUNDLE_EXTERNAL_COLUMNS_BY_PATH,
        {"verificationInfo": verification, "firestorePaths": paths},
    )
    full = hydrated.get("columns")
    if not isinstance(full, list):
        raise KaggleUsabilityError("Kaggle hydrated columns are unavailable")
    by_path = {
        str(item.get("path") or item.get("firestorePath") or ""): item
        for item in full
        if isinstance(item, dict)
    }
    if set(by_path) != set(paths):
        raise KaggleUsabilityError("Kaggle hydrated column paths changed")
    result: list[dict[str, Any]] = []
    for item, path in zip(ordered, paths, strict=True):
        merged = dict(by_path[path])
        merged["_name"] = str(item.get("name") or merged.get("name") or "")
        merged["_path"] = path
        result.append(merged)
    return result


def build_update_plan(session: _Session, context: LiveContext) -> list[dict[str, Any]]:
    resources = _live_resources(context)
    verification = _verification(context)
    plan: list[dict[str, Any]] = []
    for name, resource in resources.items():
        file_path = context.file_firestore_paths[name]
        expected_fields = (resource.get("schema") or {}).get("fields") or []
        column_updates: list[dict[str, Any]] = []
        live = _live_columns(session, context, file_path=file_path)
        if live:
            if not expected_fields:
                raise KaggleUsabilityError(
                    f"{name}: Kaggle exposes columns but local schema metadata is missing"
                )
            live_names = [str(item.get("_name") or "") for item in live]
            expected_names = [str(item.get("name") or "") for item in expected_fields]
            if live_names != expected_names:
                raise KaggleUsabilityError(
                    f"{name}: column order changed: expected {expected_names}, got {live_names}"
                )
            for field, item in zip(expected_fields, live, strict=True):
                info = item.get("tableColumnInfo")
                if not isinstance(info, dict):
                    raise KaggleUsabilityError(
                        f"{name}/{field['name']}: tableColumnInfo is missing"
                    )
                column_updates.append(
                    {
                        "firestorePath": str(item["_path"]),
                        "description": str(field.get("description") or field.get("title") or ""),
                        # Kaggle's generated UI client restores omitted proto3
                        # enum defaults before submitting the update.
                        "type": str(info.get("type") or "STRING"),
                        "extendedType": str(
                            info.get("extendedType") or "EXTENDED_DATA_TYPE_UNSPECIFIED"
                        ),
                    }
                )
        description = str(resource.get("description") or "")
        if not description:
            raise KaggleUsabilityError(f"{name}: resource description is empty")
        plan.append(
            {
                "verificationInfo": verification,
                "firestorePath": file_path,
                "description": description,
                "columns": column_updates,
            }
        )
    return plan


def get_coverage(session: _Session, context: LiveContext) -> dict[str, Any]:
    resources = _live_resources(context)
    verification = _verification(context)
    children = _post_json(
        session,
        GET_DATABUNDLE_EXTERNAL_CHILDREN,
        {
            "verificationInfo": verification,
            "firestorePath": context.root_firestore_path,
            "offset": 0,
            "count": 100,
            "depth": 1,
        },
    )
    files = children.get("files")
    if not isinstance(files, list):
        raise KaggleUsabilityError("Kaggle file metadata listing is unavailable")
    live_descriptions = {
        str(item.get("name") or ""): str(item.get("description") or "")
        for item in files
        if isinstance(item, dict) and item.get("name")
    }
    if set(live_descriptions) != set(resources):
        raise KaggleUsabilityError("Kaggle file set changed while checking coverage")
    exact_files = sum(
        live_descriptions[name] == str(resource.get("description") or "")
        for name, resource in resources.items()
    )
    present_files = sum(bool(live_descriptions[name].strip()) for name in resources)

    target_columns = 0
    exact_columns = 0
    present_columns = 0
    per_table: dict[str, dict[str, int]] = {}
    for name, resource in resources.items():
        fields = (resource.get("schema") or {}).get("fields") or []
        live = _live_columns(
            session,
            context,
            file_path=context.file_firestore_paths[name],
        )
        if not live:
            continue
        if not fields:
            raise KaggleUsabilityError(
                f"{name}: Kaggle exposes columns but local schema metadata is missing"
            )
        expected_names = [str(item.get("name") or "") for item in fields]
        live_names = [str(item.get("_name") or "") for item in live]
        if live_names != expected_names:
            raise KaggleUsabilityError(f"{name}: columns changed during coverage check")
        exact = 0
        present = 0
        for item, field in zip(live, fields, strict=True):
            info = item.get("tableColumnInfo")
            nested = info.get("description") if isinstance(info, dict) else None
            live_description = str(item.get("description") or nested or "")
            if live_description.strip():
                present += 1
            if live_description == str(field.get("description") or field.get("title") or ""):
                exact += 1
        target_columns += len(fields)
        exact_columns += exact
        present_columns += present
        per_table[name] = {"present": present, "exact": exact, "target": len(fields)}

    return {
        "present_file_descriptions": present_files,
        "exact_file_descriptions": exact_files,
        "target_file_descriptions": len(resources),
        "present_column_descriptions": present_columns,
        "exact_column_descriptions": exact_columns,
        "target_column_descriptions": target_columns,
        "file_descriptions_complete": present_files == len(resources),
        "column_descriptions_complete": present_columns == target_columns,
        "metadata_complete": present_files == len(resources) and present_columns == target_columns,
        "metadata_exact": exact_files == len(resources) and exact_columns == target_columns,
        "per_table": per_table,
    }


def get_usability(session: _Session) -> dict[str, Any]:
    response = _post_json(session, GET_DATASET_USABILITY, {"datasetId": DATASET_ID})
    rating = response.get("rating")
    if not isinstance(rating, dict):
        raise KaggleUsabilityError("Kaggle usability rating is unavailable")
    return rating


def authenticated_session() -> requests.Session:
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError as exc:
        raise KaggleUsabilityError("Kaggle CLI package is required") from exc
    api = KaggleApi()
    api.authenticate()
    client = api.build_kaggle_client()
    http_client = client.http_client()
    http_client._init_session()
    session = http_client._session
    if session is None:
        raise KaggleUsabilityError("Kaggle CLI did not initialize a session")

    # The Data Explorer mutation lives on www.kaggle.com rather than the
    # public api.kaggle.com service. Prime the browser-style anti-CSRF token
    # while retaining the CLI's bearer/API authentication. This still may be
    # rejected by Kaggle if the endpoint requires a logged-in browser session;
    # the caller reports that boundary explicitly instead of automating a browser.
    bootstrap = session.get(KAGGLE_ORIGIN, timeout=30)
    bootstrap.raise_for_status()
    xsrf_token = session.cookies.get("XSRF-TOKEN")
    if xsrf_token:
        session.headers["X-XSRF-TOKEN"] = xsrf_token
    return session


def build_browser_script(plan: list[dict[str, Any]]) -> str:
    """Build a credential-free same-origin Data Explorer synchronization script.

    Kaggle's web client authenticates this internal mutation with the logged-in
    browser session plus the JavaScript-readable XSRF/build cookies. The script
    deliberately never prints those values and never exports browser cookies.
    """

    updates = json.dumps(plan, ensure_ascii=False, separators=(",", ":"))
    return f"""(async()=>{{
const cookieValue=name=>{{
  const item=document.cookie.split('; ').find(value=>value.startsWith(name+'='));
  return item?decodeURIComponent(item.slice(name.length+1)):'';
}};
const xsrf=cookieValue('XSRF-TOKEN');
if(!xsrf) throw new Error('Kaggle XSRF-TOKEN is unavailable; sign in and reload the dataset page.');
const headers={{
  'X-XSRF-TOKEN':xsrf,
  'X-Kaggle-Build-Version':cookieValue('build-hash'),
  'Content-Type':'application/json',
  'Accept':'application/json'
}};
const updates={updates};
let completed=0;
for(const update of updates){{
  const response=await fetch('{UPDATE_DATABUNDLE_METADATA_EXTERNAL}',{{
    method:'POST',
    credentials:'same-origin',
    headers,
    body:JSON.stringify(update)
  }});
  const body=await response.text();
  const name=update.firestorePath.split('/').pop();
  if(!response.ok){{
    console.error('Kaggle metadata update failed',name,response.status,body);
    throw new Error(`${{name}}: HTTP ${{response.status}}`);
  }}
  completed+=1;
  console.log('Kaggle metadata updated',name,response.status);
  await new Promise(resolve=>setTimeout(resolve,200));
}}
console.log('Kaggle metadata batch complete',completed);
}})();
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-version",
        type=int,
        help="Dataset version to audit; defaults to the latest READY version in Kaggle history.",
    )
    parser.add_argument(
        "--metadata-path",
        type=Path,
        help=(
            "Local dataset-metadata.json to validate against the selected Kaggle version. "
            "By default the newest matching release metadata is selected automatically."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Attempt authenticated Data Explorer metadata writes after validation.",
    )
    parser.add_argument(
        "--browser-script",
        nargs="?",
        const=BROWSER_SCRIPT_PATH,
        type=Path,
        help=(
            "Write a credential-free same-origin browser-console batch script. "
            "With no path, writes tmp_research/kaggle_usability_browser_sync.js."
        ),
    )
    return parser.parse_args()


def main() -> int:
    global METADATA_PATH
    args = parse_args()
    public = requests.Session()
    version_number = args.dataset_version or latest_ready_version(public)
    context = load_live_context(public, version_number=version_number)
    METADATA_PATH = select_metadata_path(context, args.metadata_path)
    plan = build_update_plan(public, context)
    before = get_coverage(public, context)
    usability = get_usability(public)
    report: dict[str, Any] = {
        "dataset": DATASET_REF,
        "mode": (
            "apply"
            if args.apply
            else "browser-script"
            if args.browser_script is not None
            else "dry-run"
        ),
        "context": {
            "dataset_id": context.dataset_id,
            "dataset_version_id": context.dataset_version_id,
            "databundle_version_id": context.databundle_version_id,
            "version_number": context.version_number,
        },
        "metadata_path": str(METADATA_PATH),
        "plan": {
            "files": len(plan),
            "columns": sum(len(item["columns"]) for item in plan),
        },
        "coverage_before": before,
        "usability_before": usability,
        "usability_read_model_stale": bool(
            before["metadata_complete"] and float(usability.get("score", 0) or 0) < 1.0
        ),
    }

    exit_code = 0
    if args.browser_script is not None:
        browser_script_path = args.browser_script
        if not browser_script_path.is_absolute():
            browser_script_path = ROOT / browser_script_path
        browser_script_path.parent.mkdir(parents=True, exist_ok=True)
        browser_script_path.write_text(build_browser_script(plan), encoding="utf-8")
        report["browser_script"] = str(browser_script_path)

    if args.apply:
        authenticated = authenticated_session()
        try:
            for update in plan:
                _post_json(authenticated, UPDATE_DATABUNDLE_METADATA_EXTERNAL, update)
        except KaggleUsabilityError as exc:
            report["apply_error"] = str(exc)
            exit_code = 3
        else:
            after = before
            for _ in range(8):
                time.sleep(2)
                after = get_coverage(requests.Session(), context)
                if after["metadata_complete"]:
                    break
            report["coverage_after"] = after
            report["usability_after"] = get_usability(requests.Session())
            if not after["metadata_complete"]:
                exit_code = 2

    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"WROTE {AUDIT_PATH}")
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KaggleUsabilityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
