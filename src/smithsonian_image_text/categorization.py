"""Deterministic high-level category assignment for Phase 4 sampling."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


TEXT_FIELDS = (
    "title",
    "description",
    "object_type",
    "topics",
    "usage_flags",
    "scientific_name",
)


def _text(candidate: Mapping[str, Any]) -> str:
    return " ".join(str(candidate.get(field) or "") for field in TEXT_FIELDS).casefold()


def _has_any(text: str, values: list[str] | tuple[str, ...]) -> bool:
    return any(str(value).casefold() in text for value in values)


def assign_category(candidate: Mapping[str, Any], config: Mapping[str, Any]) -> str:
    """Assign exactly one broad category without using image pixels or generated text."""
    unit = str(candidate.get("unit_code") or "").upper()
    groups = config.get("unit_groups") or {}
    keywords = config.get("keywords") or {}
    text = _text(candidate)

    natural_units = {str(value).upper() for value in groups.get("natural_history") or []}
    if unit in natural_units:
        return "natural_history"

    if unit in {str(value).upper() for value in groups.get("space") or []}:
        return "space_aviation"

    if unit in {str(value).upper() for value in groups.get("postal") or []}:
        return "coins_stamps_documents"

    if unit in {str(value).upper() for value in groups.get("art") or []}:
        return "art"

    if unit in {str(value).upper() for value in groups.get("asian_art") or []}:
        if _has_any(text, keywords.get("archaeology") or []):
            return "archaeology"
        return "art"

    if unit in {str(value).upper() for value in groups.get("design") or []}:
        if _has_any(text, keywords.get("fine_art") or []):
            return "art"
        return "decorative_arts_design"

    if unit in {str(value).upper() for value in groups.get("history") or []}:
        if _has_any(text, keywords.get("space_aviation") or []):
            return "space_aviation"
        if _has_any(text, keywords.get("archaeology") or []):
            return "archaeology"
        if _has_any(text, keywords.get("coins_stamps_documents") or []):
            return "coins_stamps_documents"
        if _has_any(text, keywords.get("science_technology") or []):
            return "science_technology"
        return "historical_objects"

    return "other_objects"
