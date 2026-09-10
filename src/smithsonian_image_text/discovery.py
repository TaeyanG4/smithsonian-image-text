"""Metadata-only discovery against the official Smithsonian bulk S3 export."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .schema import iter_canonical_candidates


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


def _lines(response: requests.Response) -> list[str]:
    response.raise_for_status()
    return [line.strip() for line in response.text.splitlines() if line.strip()]


def fetch_unit_index_urls(
    session: requests.Session, index_url: str = BULK_INDEX_URL, timeout: float = 60
) -> dict[str, str]:
    response = session.get(index_url, timeout=timeout)
    result: dict[str, str] = {}
    for url in _lines(response):
        unit = PurePosixPath(url).parent.name.upper()
        result[unit] = url
    return result


def fetch_shard_urls(
    session: requests.Session, unit_index_url: str, timeout: float = 60
) -> list[str]:
    return _lines(session.get(unit_index_url, timeout=timeout))


def deterministic_shard_order(urls: Sequence[str], *, seed: str, unit_code: str) -> list[str]:
    """Return a stable pseudo-random order without relying on API random sort."""

    def rank(url: str) -> bytes:
        name = PurePosixPath(url).name
        return hashlib.sha256(f"{seed}:{unit_code.upper()}:{name}".encode()).digest()

    return sorted(urls, key=rank)


def iter_ndjson_records(
    session: requests.Session, url: str, *, timeout: float = 60, strict: bool = True
) -> Iterator[dict[str, Any]]:
    """Stream one official bulk shard line-by-line; never load the shard into memory."""
    with session.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        response.encoding = "utf-8"
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            try:
                value = json.loads(raw_line)
            except (TypeError, json.JSONDecodeError) as exc:
                if strict:
                    raise ValueError(f"Invalid NDJSON record in {url}") from exc
                continue
            if isinstance(value, dict):
                yield value


@dataclass
class DiscoveryStats:
    records_seen: int = 0
    candidates_emitted: int = 0
    shards_read: int = 0
    shard_urls_read: list[str] = field(default_factory=list)
    per_unit_records: Counter[str] = field(default_factory=Counter)
    per_unit_candidates: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {
            "records_seen": self.records_seen,
            "candidates_emitted": self.candidates_emitted,
            "shards_read": self.shards_read,
            "shard_urls_read": self.shard_urls_read,
            "per_unit_records": dict(self.per_unit_records),
            "per_unit_candidates": dict(self.per_unit_candidates),
        }


def discover_candidates(
    *,
    units: Sequence[str],
    target: int,
    max_per_unit: int = 12_000,
    max_shards_per_unit: int = 64,
    seed: str = "smithsonian-image-text-v1",
    max_side: int = 512,
    timeout: float = 60,
    index_url: str = BULK_INDEX_URL,
    session: requests.Session | None = None,
) -> tuple[Iterator[dict[str, Any]], DiscoveryStats]:
    """Round-robin deterministic Smithsonian metadata discovery.

    The returned iterator reads at most one shard per active unit per round. This
    prevents a very large unit from consuming the global target before smaller
    museums are represented. Rights are filtered at the record and individual
    media level while still in metadata space; no image bytes are downloaded.
    """
    if target <= 0:
        raise ValueError("target must be positive")
    owned_session = session is None
    http = session or build_session()
    stats = DiscoveryStats()

    unit_indexes = fetch_unit_index_urls(http, index_url=index_url, timeout=timeout)
    normalized_units = [unit.upper() for unit in units if unit.upper() in unit_indexes]
    shard_map = {
        unit: deterministic_shard_order(
            fetch_shard_urls(http, unit_indexes[unit], timeout=timeout), seed=seed, unit_code=unit
        )[:max_shards_per_unit]
        for unit in normalized_units
    }

    # First pass gives every configured unit an equal opportunity to contribute.
    # If some units cannot fill their share, a second pass relaxes to max_per_unit.
    soft_per_unit = min(max_per_unit, math.ceil(target / max(1, len(normalized_units))))

    def generate() -> Iterator[dict[str, Any]]:
        try:
            shard_positions = {unit: 0 for unit in normalized_units}
            for unit_limit in (soft_per_unit, max_per_unit):
                while True:
                    made_progress = False
                    for unit in normalized_units:
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
                        for record in iter_ndjson_records(http, shard_url, timeout=timeout):
                            stats.records_seen += 1
                            stats.per_unit_records[unit] += 1
                            for candidate in iter_canonical_candidates(
                                record, cc0_only=True, max_side=max_side
                            ):
                                if stats.per_unit_candidates[unit] >= unit_limit:
                                    break
                                stats.candidates_emitted += 1
                                stats.per_unit_candidates[unit] += 1
                                yield candidate
                                if stats.candidates_emitted >= target:
                                    return
                    if not made_progress:
                        break
        finally:
            if owned_session:
                http.close()

    return generate(), stats
