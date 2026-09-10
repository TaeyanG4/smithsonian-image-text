"""Retrying, bounded, atomic image download helpers for pilot and production."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from .image_processing import normalize_to_jpeg


_THREAD_LOCAL = threading.local()


def _session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=4, max_retries=0))
        session.headers["User-Agent"] = "smithsonian-image-text/0.1 image-pilot"
        _THREAD_LOCAL.session = session
    return session


def download_and_process(
    candidate: dict[str, Any],
    *,
    image_id: int,
    output_dir: Path,
    max_side: int,
    jpeg_quality: int,
    timeout: float,
    max_attempts: int,
    retry_backoff_seconds: float,
    max_download_bytes: int,
    phash_size: int = 8,
    phash_highfreq_factor: int = 4,
    min_max_side: int | None = None,
) -> dict[str, Any]:
    """Download one candidate to a temp file, normalize it, and return an audit row."""
    started = time.perf_counter()
    url = str(candidate.get("image_url") or candidate.get("media_url") or "").strip()
    file_name = f"{image_id:08d}.jpg"
    destination = output_dir / file_name
    base = {
        "image_id": image_id,
        "file_name": file_name,
        "object_id": candidate.get("object_id"),
        "media_id": candidate.get("media_id"),
        "unit_code": candidate.get("unit_code"),
        "institution": candidate.get("institution"),
        "category": candidate.get("category"),
        "category_code": candidate.get("category_code"),
        "source_url": candidate.get("source_url"),
        "media_url": candidate.get("media_url"),
        "image_url": url,
        "http_status": None,
        "content_type": None,
        "attempts": 0,
        "download_bytes": None,
        "download_seconds": None,
        "original_width": None,
        "original_height": None,
        "original_format": None,
        "final_width": None,
        "final_height": None,
        "final_bytes": None,
        "sha256": None,
        "phash": None,
        "decode_success": False,
        "status": "failed",
        "error": None,
        "processing_seconds": None,
        "total_seconds": None,
    }
    if not url:
        base["error"] = "MISSING_IMAGE_URL"
        base["total_seconds"] = time.perf_counter() - started
        return base

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / ".tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    retryable_statuses = {408, 425, 429, 500, 502, 503, 504}

    for attempt in range(1, max_attempts + 1):
        base["attempts"] = attempt
        temp_path: Path | None = None
        try:
            download_started = time.perf_counter()
            with _session().get(url, stream=True, timeout=timeout) as response:
                base["http_status"] = response.status_code
                base["content_type"] = response.headers.get("Content-Type")
                if response.status_code != 200:
                    if response.status_code in retryable_statuses and attempt < max_attempts:
                        raise requests.RequestException(f"retryable HTTP {response.status_code}")
                    base["error"] = f"HTTP_{response.status_code}"
                    break
                content_type = (
                    str(base["content_type"] or "").split(";", 1)[0].strip().casefold()
                )
                if content_type and not content_type.startswith("image/"):
                    base["error"] = f"UNEXPECTED_MIME:{content_type}"
                    break

                with tempfile.NamedTemporaryFile(
                    dir=temp_dir, suffix=".download", delete=False
                ) as tmp:
                    temp_path = Path(tmp.name)
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if downloaded > max_download_bytes:
                            raise ValueError("DOWNLOAD_TOO_LARGE")
                        tmp.write(chunk)
            base["download_bytes"] = downloaded
            base["download_seconds"] = time.perf_counter() - download_started
            result = normalize_to_jpeg(
                temp_path,
                destination,
                max_side=max_side,
                quality=jpeg_quality,
                phash_size=phash_size,
                phash_highfreq_factor=phash_highfreq_factor,
                min_max_side=min_max_side,
            )
            base.update(
                {
                    "original_width": result.original_width,
                    "original_height": result.original_height,
                    "original_format": result.original_format,
                    "final_width": result.final_width,
                    "final_height": result.final_height,
                    "final_bytes": result.final_bytes,
                    "sha256": result.sha256,
                    "phash": result.phash,
                    "decode_success": True,
                    "status": "success",
                    "error": None,
                    "processing_seconds": result.processing_seconds,
                }
            )
            break
        except requests.RequestException as exc:
            base["error"] = f"REQUEST_ERROR:{type(exc).__name__}"
            if attempt >= max_attempts:
                break
            time.sleep(retry_backoff_seconds * (2 ** (attempt - 1)))
        except Exception as exc:  # Pillow decode failures and bounded-size failures are audited.
            base["error"] = f"{type(exc).__name__}:{str(exc)[:200]}"
            break
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    base["total_seconds"] = time.perf_counter() - started
    if base["status"] != "success":
        destination.unlink(missing_ok=True)
    return base
