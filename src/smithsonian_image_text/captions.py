"""Deterministic model-ready text composed only from Smithsonian metadata."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


TEXT_SOURCE = "smithsonian_metadata_composed"


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip(" ;,.")
    return text or None


def _truncate_words(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    clipped = text[: max(0, limit - 1)].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip(" ;,.")
    return clipped + "…"


def build_model_text(
    candidate: Mapping[str, Any], *, max_chars: int = 512, description_max_chars: int = 240
) -> str:
    """Compose a compact factual text field without inference or free-form generation."""
    if max_chars <= 0 or description_max_chars < 0:
        raise ValueError("text length limits must be positive/non-negative")
    parts: list[str] = []
    seen: set[str] = set()

    def add(label: str | None, value: Any) -> None:
        text = _clean(value)
        if not text:
            return
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        parts.append(text if label is None else f"{label}: {text}")

    add(None, candidate.get("title"))
    add("Object type", candidate.get("object_type"))
    add("Scientific name", candidate.get("scientific_name"))
    add("Creator", candidate.get("creator"))
    add("Date", candidate.get("date"))
    add("Place", candidate.get("place"))
    add("Topics", candidate.get("topics"))
    description = _clean(candidate.get("description"))
    if description and description.casefold() not in seen and description_max_chars:
        parts.append(f"Description: {_truncate_words(description, description_max_chars)}")

    text = ". ".join(parts) + ("." if parts else "")
    if len(text) > max_chars:
        text = _truncate_words(text, max_chars - 1).rstrip(".") + "."
    return text
