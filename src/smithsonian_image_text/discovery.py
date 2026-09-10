"""Metadata-only discovery against the official Smithsonian bulk S3 export."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .schema import descriptive, iter_canonical_candidates, iter_media


BULK_INDEX_URL = (
    "https://smithsonian-open-access.s3-us-west-2.amazonaws.com/metadata/edan/index.txt"
)


def build_session() -> requests.Session:
    """HTTP session with bounded retries for read-only Smithsonian metadata requests."""
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "smithsonian-image-text/0.1 metadata-discovery"
    return session


def _response_identity(response: requests.Response, body: bytes) -> dict[str, Any]:
    return {
        "url": response.url,
        "status_code": response.status_code,
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
        "content_length": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _lines(response: requests.Response) -> list[str]:
    response.raise_for_status()
    return [line.strip() for line in response.text.splitlines() if line.strip()]


def fetch_unit_index_urls(
    session: requests.Session,
    index_url: str = BULK_INDEX_URL,
    timeout: float = 60,
    identity_sink: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    response = session.get(index_url, timeout=timeout)
    response.raise_for_status()
    body = response.content
    if identity_sink is not None:
        identity_sink.append({"kind": "top_index", **_response_identity(response, body)})
    result: dict[str, str] = {}
    for url in _lines(response):
        unit = PurePosixPath(url).parent.name.upper()
        result[unit] = url
    return result


def fetch_shard_urls(
    session: requests.Session,
    unit_index_url: str,
    timeout: float = 60,
    identity_sink: list[dict[str, Any]] | None = None,
) -> list[str]:
    response = session.get(unit_index_url, timeout=timeout)
    response.raise_for_status()
    body = response.content
    if identity_sink is not None:
        identity_sink.append({"kind": "unit_index", **_response_identity(response, body)})
    return _lines(response)


def deterministic_shard_order(urls: Sequence[str], *, seed: str, unit_code: str) -> list[str]:
    """Return a stable pseudo-random order without relying on API random sort."""

    def rank(url: str) -> bytes:
        name = PurePosixPath(url).name
        return hashlib.sha256(f"{seed}:{unit_code.upper()}:{name}".encode()).digest()

    return sorted(urls, key=rank)


def iter_ndjson_records(
    session: requests.Session,
    url: str,
    *,
    timeout: float = 60,
    strict: bool = True,
    identity_sink: list[dict[str, Any]] | None = None,
) -> Iterator[dict[str, Any]]:
    """Read one official bulk shard after a complete-length download to a temp file.

    `requests` retries initial HTTP failures, but an interrupted streamed response can
    otherwise leave a truncated JSON line after some records have already been yielded.
    Spooling one shard to disk first lets us verify Content-Length before parsing while
    still keeping large shards out of memory. The temporary copy is removed afterward.
    """
    temp_path: Path | None = None
    last_error: Exception | None = None
    for attempt in range(4):
        temp_file = tempfile.NamedTemporaryFile(prefix="smithsonian-shard-", suffix=".ndjson", delete=False)
        temp_path = Path(temp_file.name)
        bytes_written = 0
        digest = hashlib.sha256()
        response_identity: dict[str, Any] | None = None
        try:
            with temp_file:
                with session.get(url, stream=True, timeout=timeout) as response:
                    response.raise_for_status()
                    expected_header = response.headers.get("Content-Length")
                    expected = int(expected_header) if expected_header and expected_header.isdigit() else None
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        temp_file.write(chunk)
                        digest.update(chunk)
                        bytes_written += len(chunk)
                    response_identity = {
                        "kind": "shard",
                        "url": response.url,
                        "status_code": response.status_code,
                        "etag": response.headers.get("ETag"),
                        "last_modified": response.headers.get("Last-Modified"),
                        "content_length": bytes_written,
                        "sha256": digest.hexdigest(),
                    }
            if expected is not None and bytes_written != expected:
                raise OSError(
                    f"Truncated Smithsonian shard {url}: got {bytes_written} bytes, expected {expected}"
                )
            break
        except (OSError, requests.RequestException) as exc:
            last_error = exc
            temp_path.unlink(missing_ok=True)
            temp_path = None
            if attempt == 3:
                raise OSError(f"Unable to download complete Smithsonian shard: {url}") from exc
            time.sleep(0.5 * (2**attempt))

    if temp_path is None:
        raise OSError(f"Unable to materialize Smithsonian shard: {url}") from last_error
    if identity_sink is not None and response_identity is not None:
        identity_sink.append(response_identity)

    try:
        with temp_path.open("r", encoding="utf-8") as stream:
            for raw_line in stream:
                if not raw_line.strip():
                    continue
                try:
                    value = json.loads(raw_line)
                except (TypeError, json.JSONDecodeError) as exc:
                    if strict:
                        raise ValueError(f"Invalid NDJSON record in {url}") from exc
                    continue
                if isinstance(value, dict):
                    yield value
    finally:
        temp_path.unlink(missing_ok=True)


@dataclass
class DiscoveryStats:
    records_seen: int = 0
    candidates_emitted: int = 0
    shards_read: int = 0
    shard_urls_read: list[str] = field(default_factory=list)
    per_unit_records: Counter[str] = field(default_factory=Counter)
    per_unit_candidates: Counter[str] = field(default_factory=Counter)
    record_metadata_access_seen: Counter[str] = field(default_factory=Counter)
    media_types_seen: Counter[str] = field(default_factory=Counter)
    image_media_access_seen: Counter[str] = field(default_factory=Counter)
    records_with_image_media: int = 0
    records_with_cc0_candidates: int = 0
    candidate_records_emitted: int = 0
    candidate_records_truncated: int = 0
    candidate_media_truncated: int = 0
    source_index_manifest: list[dict[str, Any]] = field(default_factory=list)
    shard_manifest: list[dict[str, Any]] = field(default_factory=list)
    normalized_units: list[str] = field(default_factory=list)
    effective_unit_caps: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "records_seen": self.records_seen,
            "candidates_emitted": self.candidates_emitted,
            "shards_read": self.shards_read,
            "shard_urls_read": self.shard_urls_read,
            "per_unit_records": dict(self.per_unit_records),
            "per_unit_candidates": dict(self.per_unit_candidates),
            "record_metadata_access_seen": dict(self.record_metadata_access_seen),
            "media_types_seen": dict(self.media_types_seen),
            "image_media_access_seen": dict(self.image_media_access_seen),
            "records_with_image_media": self.records_with_image_media,
            "records_with_cc0_candidates": self.records_with_cc0_candidates,
            "candidate_records_emitted": self.candidate_records_emitted,
            "candidate_records_truncated": self.candidate_records_truncated,
            "candidate_media_truncated": self.candidate_media_truncated,
            "source_index_manifest": self.source_index_manifest,
            "shard_manifest": self.shard_manifest,
            "normalized_units": self.normalized_units,
            "effective_unit_caps": self.effective_unit_caps,
        }


def normalize_units(units: Sequence[str], available_units: Sequence[str]) -> list[str]:
    """Normalize/deduplicate requested unit codes and fail on unknown units."""
    available = {str(unit).upper() for unit in available_units}
    normalized: list[str] = []
    unknown: list[str] = []
    for value in units:
        unit = str(value).upper()
        if unit not in available:
            unknown.append(unit)
            continue
        if unit not in normalized:
            normalized.append(unit)
    if unknown:
        raise ValueError(f"Unknown Smithsonian unit code(s): {', '.join(dict.fromkeys(unknown))}")
    if not normalized:
        raise ValueError("At least one valid Smithsonian unit code is required")
    return normalized


def effective_unit_caps(
    units: Sequence[str], *, max_per_unit: int, configured_caps: Mapping[str, int] | None = None
) -> dict[str, int]:
    """Apply the global/CLI cap as a true upper bound over configured unit caps."""
    if max_per_unit <= 0:
        raise ValueError("max_per_unit must be positive")
    configured = {str(key).upper(): int(value) for key, value in (configured_caps or {}).items()}
    result: dict[str, int] = {}
    for unit in units:
        configured_cap = configured.get(unit, max_per_unit)
        if configured_cap <= 0:
            raise ValueError(f"Configured candidate cap for {unit} must be positive")
        result[unit] = min(max_per_unit, configured_cap)
    return result


def discover_candidates(
    *,
    units: Sequence[str],
    target: int,
    max_per_unit: int = 12_000,
    unit_candidate_caps: Mapping[str, int] | None = None,
    max_shards_per_unit: int = 64,
    shard_offset: int = 0,
    seed: str = "smithsonian-image-text-v1",
    max_side: int = 512,
    timeout: float = 60,
    index_url: str = BULK_INDEX_URL,
    session: requests.Session | None = None,
    candidate_record_callback: Callable[[str, str, dict[str, Any]], None] | None = None,
) -> tuple[Iterator[dict[str, Any]], DiscoveryStats]:
    """Round-robin deterministic Smithsonian metadata discovery.

    The returned iterator reads at most one shard per active unit per round. This
    prevents a very large unit from consuming the global target before smaller
    museums are represented. Rights are filtered at the record and individual
    media level while still in metadata space; no image bytes are downloaded.
    """
    if target <= 0:
        raise ValueError("target must be positive")
    if max_shards_per_unit <= 0:
        raise ValueError("max_shards_per_unit must be positive")
    if shard_offset < 0:
        raise ValueError("shard_offset must be zero or positive")
    owned_session = session is None
    http = session or build_session()
    stats = DiscoveryStats()

    unit_indexes = fetch_unit_index_urls(
        http, index_url=index_url, timeout=timeout, identity_sink=stats.source_index_manifest
    )
    normalized_units = normalize_units(units, unit_indexes)
    caps = effective_unit_caps(
        normalized_units, max_per_unit=max_per_unit, configured_caps=unit_candidate_caps
    )
    stats.normalized_units = list(normalized_units)
    stats.effective_unit_caps = dict(caps)
    shard_map = {}
    for unit in normalized_units:
        ordered = deterministic_shard_order(
            fetch_shard_urls(
                http,
                unit_indexes[unit],
                timeout=timeout,
                identity_sink=stats.source_index_manifest,
            ),
            seed=seed,
            unit_code=unit,
        )
        shard_map[unit] = ordered[shard_offset : shard_offset + max_shards_per_unit]

    def generate() -> Iterator[dict[str, Any]]:
        try:
            shard_positions = {unit: 0 for unit in normalized_units}
            while True:
                made_progress = False
                for unit in normalized_units:
                    unit_limit = caps[unit]
                    if stats.candidates_emitted >= target:
                        return
                    if stats.per_unit_candidates[unit] >= unit_limit:
                        continue
                    pos = shard_positions[unit]
                    shards = shard_map[unit]
                    if pos >= len(shards):
                        continue
                    made_progress = True
                    shard_positions[unit] += 1
                    stats.shards_read += 1
                    shard_url = shards[pos]
                    stats.shard_urls_read.append(shard_url)
                    for record in iter_ndjson_records(
                        http,
                        shard_url,
                        timeout=timeout,
                        identity_sink=stats.shard_manifest,
                    ):
                        stats.records_seen += 1
                        stats.per_unit_records[unit] += 1
                        metadata_access = str(
                            ((descriptive(record).get("metadata_usage") or {}).get("access") or "")
                        )
                        stats.record_metadata_access_seen[metadata_access] += 1
                        medias = list(iter_media(record))
                        has_image_media = False
                        for media in medias:
                            media_type = str(media.get("type") or "")
                            stats.media_types_seen[media_type] += 1
                            if media_type == "Images":
                                has_image_media = True
                                access = str(((media.get("usage") or {}).get("access") or ""))
                                stats.image_media_access_seen[access] += 1
                        if has_image_media:
                            stats.records_with_image_media += 1

                        candidates = list(
                            iter_canonical_candidates(record, cc0_only=True, max_side=max_side)
                        )
                        if candidates:
                            stats.records_with_cc0_candidates += 1

                        remaining_unit = unit_limit - stats.per_unit_candidates[unit]
                        remaining_global = target - stats.candidates_emitted
                        remaining = max(0, min(remaining_unit, remaining_global))
                        emitted_candidates = candidates[:remaining]
                        truncated = len(candidates) - len(emitted_candidates)
                        if truncated > 0:
                            stats.candidate_records_truncated += 1
                            stats.candidate_media_truncated += truncated

                        if emitted_candidates and candidate_record_callback is not None:
                            candidate_record_callback(unit, shard_url, record)
                        if emitted_candidates:
                            stats.candidate_records_emitted += 1

                        for candidate in emitted_candidates:
                            candidate["source_shard_url"] = shard_url
                            stats.candidates_emitted += 1
                            stats.per_unit_candidates[unit] += 1
                            yield candidate

                        if stats.candidates_emitted >= target:
                            return
                        if stats.per_unit_candidates[unit] >= unit_limit:
                            break
                if not made_progress:
                    break
        finally:
            if owned_session:
                http.close()

    return generate(), stats
