"""Image normalization and deterministic perceptual hashing for the collection pipeline."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


@dataclass(frozen=True)
class ImageProcessResult:
    original_width: int
    original_height: int
    original_format: str | None
    final_width: int
    final_height: int
    final_bytes: int
    sha256: str
    phash: str
    processing_seconds: float


def perceptual_hash(image: Image.Image, *, hash_size: int = 8, highfreq_factor: int = 4) -> str:
    """Return a conventional DCT pHash as a fixed-width hexadecimal string.

    The implementation is local and deterministic, avoiding an additional runtime
    dependency. The DC coefficient is excluded from the median threshold.
    """
    if hash_size <= 0 or highfreq_factor <= 0:
        raise ValueError("hash_size and highfreq_factor must be positive")
    size = hash_size * highfreq_factor
    grayscale = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    pixels = np.asarray(grayscale, dtype=np.float64)

    x = np.arange(size, dtype=np.float64)
    u = np.arange(size, dtype=np.float64)[:, None]
    transform = np.cos((np.pi / (2.0 * size)) * u * (2.0 * x + 1.0))
    dct = transform @ pixels @ transform.T
    low = dct[:hash_size, :hash_size].flatten()
    median = float(np.median(low[1:])) if low.size > 1 else float(low[0])
    bits = low > median
    value = 0
    for bit in bits:
        value = (value << 1) | int(bool(bit))
    width = (bits.size + 3) // 4
    return f"{value:0{width}x}"


def phash_distance(left: str, right: str) -> int:
    """Hamming distance between same-width hexadecimal perceptual hashes."""
    if len(left) != len(right):
        raise ValueError("pHash values must have the same width")
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _rgb(image: Image.Image) -> Image.Image:
    """Convert to RGB, compositing transparency onto white rather than black."""
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_to_jpeg(
    source: Path,
    destination: Path,
    *,
    max_side: int = 512,
    quality: int = 84,
    phash_size: int = 8,
    phash_highfreq_factor: int = 4,
    min_max_side: int | None = None,
) -> ImageProcessResult:
    """Decode, orient, RGB-convert, resize, encode, verify, and atomically save a JPEG."""
    if max_side <= 0:
        raise ValueError("max_side must be positive")
    if not 1 <= quality <= 95:
        raise ValueError("JPEG quality must be between 1 and 95")
    started = time.perf_counter()
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.unlink(missing_ok=True)

    with Image.open(source) as opened:
        original_width, original_height = opened.size
        original_format = opened.format
        opened.load()
        normalized = _rgb(ImageOps.exif_transpose(opened))

    if min_max_side is not None and max(normalized.size) < min_max_side:
        raise ValueError(
            f"LOW_RESOLUTION:max_side={max(normalized.size)} below minimum {min_max_side}"
        )

    if max(normalized.size) > max_side:
        normalized.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    phash = perceptual_hash(
        normalized, hash_size=phash_size, highfreq_factor=phash_highfreq_factor
    )
    normalized.save(partial, format="JPEG", quality=quality, optimize=True)

    with Image.open(partial) as verify:
        verify.load()
        final_width, final_height = verify.size
        if max(final_width, final_height) > max_side:
            partial.unlink(missing_ok=True)
            raise ValueError("Normalized image exceeds configured max side")

    final_bytes = partial.stat().st_size
    sha256 = _sha256_file(partial)
    os.replace(partial, destination)
    return ImageProcessResult(
        original_width=original_width,
        original_height=original_height,
        original_format=original_format,
        final_width=final_width,
        final_height=final_height,
        final_bytes=final_bytes,
        sha256=sha256,
        phash=phash,
        processing_seconds=time.perf_counter() - started,
    )
