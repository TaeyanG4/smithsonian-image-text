"""Conservative, explainable metadata eligibility rules for V1."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


_IDISH_TITLE = re.compile(r"^(?:object|item|specimen|record)\s*[-#:]*\s*\d+$", re.I)


@dataclass(frozen=True)
class EligibilityDecision:
    status: str
    reasons: tuple[str, ...]


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _contains_term(text: str, term: Any) -> bool:
    """Match a review term as a word/phrase, not as an arbitrary substring.

    For example, the trigger ``grave`` must not match the ordinary museum word
    ``engraved``.
    """
    needle = str(term).strip().casefold()
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text) is not None


def evaluate_candidate(candidate: Mapping[str, Any], rules: Mapping[str, Any]) -> EligibilityDecision:
    """Classify a canonical media candidate as eligible/review_required/rejected."""
    reasons: list[str] = []
    rights = rules.get("rights") or {}

    metadata_rights = str(candidate.get("metadata_rights") or "")
    media_rights = str(candidate.get("media_rights") or "")
    media_type = str(candidate.get("media_type") or "")

    if metadata_rights not in set(rights.get("accepted_metadata_access") or []):
        reasons.append("NO_CC0_METADATA" if metadata_rights else "RIGHTS_UNCLEAR")
    if media_type not in set(rights.get("accepted_media_types") or []):
        reasons.append("NO_IMAGE")
    if media_rights not in set(rights.get("accepted_media_access") or []):
        reasons.append("NO_CC0_MEDIA" if media_rights else "RIGHTS_UNCLEAR")

    for field, required in (rules.get("required") or {}).items():
        if required and not _present(candidate.get(field)):
            reasons.append(f"MISSING_{field.upper()}")

    if reasons:
        return EligibilityDecision("rejected", tuple(dict.fromkeys(reasons)))

    text_rules = rules.get("text") or {}
    useful_fields = text_rules.get("useful_fields") or []
    useful_count = sum(_present(candidate.get(field)) for field in useful_fields)
    title = str(candidate.get("title") or "").strip()
    reject_exact = {str(x).casefold() for x in text_rules.get("reject_exact_casefold") or []}
    if title.casefold() in reject_exact or _IDISH_TITLE.fullmatch(title):
        useful_count -= 1
    if useful_count < int(text_rules.get("minimum_non_id_fields", 2)):
        return EligibilityDecision("rejected", ("LOW_TEXT_QUALITY",))

    sensitive = rules.get("sensitive_review") or {}
    unit = str(candidate.get("unit_code") or "").upper()
    review_reasons: list[str] = []
    rights_context = " ".join(
        str(candidate.get(field) or "") for field in ("object_rights", "indexed_media_rights")
    ).casefold()
    if any(
        _contains_term(rights_context, term) for term in rights.get("review_context_terms") or []
    ):
        review_reasons.append("RIGHTS_CONTEXT_REVIEW")

    haystack = " ".join(
        str(candidate.get(field) or "")
        for field in (
            "title",
            "description",
            "media_caption",
            "object_type",
            "topics",
            "culture",
            "scientific_name",
            "physical_description",
            "creator",
            "place",
            "alt_text",
            "media_description",
            "object_rights",
            "indexed_media_rights",
        )
    ).casefold()

    review = unit in {str(x).upper() for x in sensitive.get("unit_codes") or []}
    review = review or any(_contains_term(haystack, keyword) for keyword in sensitive.get("review_keywords") or [])

    if unit in {str(x).upper() for x in sensitive.get("modern_portrait_unit_codes") or []}:
        review = review or any(
            _contains_term(haystack, keyword) for keyword in sensitive.get("modern_portrait_keywords") or []
        )

    if review:
        review_reasons.append("SENSITIVE_REVIEW")
    if review_reasons:
        return EligibilityDecision("review_required", tuple(dict.fromkeys(review_reasons)))
    return EligibilityDecision("eligible", ())
