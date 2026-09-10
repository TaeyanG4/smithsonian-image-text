"""Small helpers for optional model-derived embedding artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np


def l2_normalize(array: np.ndarray, *, eps: float = 1e-12) -> np.ndarray:
    """Return row-wise L2-normalized float32 vectors."""
    values = np.asarray(array, dtype=np.float32)
    if values.ndim != 2:
        raise ValueError("embedding array must be 2-dimensional")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(norms, eps)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
