"""Canonical mapping from Smithsonian EDAN records to media-level candidates."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(value: Any) -> str | None:
    """Return normalized plain text without inventing missing information."""
    if value is None:
        return None
    text = html.unescape(str(value))
    text = _TAG_RE.sub("", text)
    text = " ".join(text.split())
    return text or None


def _items(record: Mapping[str, Any], group: str) -> list[Mapping[str, Any]]:
    content = record.get("content") or {}
    freetext = content.get("freetext") or {}
    values = freetext.get(group) or []
    return [item for item in values if isinstance(item, Mapping)]


def _freetext_values(
    record: Mapping[str, Any],
    group: str,
    label_contains: Iterable[str] | None = None,
) -> list[str]:
    needles = [x.casefold() for x in label_contains or []]
    result: list[str] = []
    for item in _items(record, group):
        label = clean_text(item.get("label")) or ""
        if needles and not any(needle in label.casefold() for needle in needles):
            continue
        value = clean_text(item.get("content"))
        if value and value not in result:
            result.append(value)
    return result


def _structured_values(record: Mapping[str, Any], key: str) -> list[str]:
    values = ((record.get("content") or {}).get("indexedStructured") or {}).get(key) or []
    result: list[str] = []
    for value in values:
        if isinstance(value, (str, int, float)):
            text = clean_text(value)
            if text and text not in result:
                result.append(text)
    return result


def _join(values: Iterable[str]) -> str | None:
    unique: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text not in unique:
            unique.append(text)
    return "; ".join(unique) if unique else None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def descriptive(record: Mapping[str, Any]) -> Mapping[str, Any]:
    return (record.get("content") or {}).get("descriptiveNonRepeating") or {}


def iter_media(record: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    online = descriptive(record).get("online_media") or {}
    for media in online.get("media") or []:
        if isinstance(media, Mapping):
            yield media


def media_is_cc0_image(media: Mapping[str, Any]) -> bool:
    return media.get("type") == "Images" and ((media.get("usage") or {}).get("access") == "CC0")


def record_metadata_is_cc0(record: Mapping[str, Any]) -> bool:
    return ((descriptive(record).get("metadata_usage") or {}).get("access") == "CC0")


def preferred_ids_derivative_url(media_url: str | None, max_side: int = 512) -> str | None:
    """Build the official IDS derivative form observed in Smithsonian metadata.

    Two currently observed forms are supported:
    - ``.../deliveryService?id=<IDS_ID>`` -> add/replace ``max=<pixels>``
    - ``.../deliveryService/id/ark:/...`` -> append ``/<pixels>``

    Non-IDS URLs are returned unchanged; downstream download code must still
    validate MIME type and decoded dimensions.
    """
    media_url = clean_text(media_url)
    if not media_url:
        return None
    parsed = urlparse(media_url)
    if parsed.netloc.casefold() != "ids.si.edu":
        return media_url

    if "/ids/deliveryService/id/" in parsed.path:
        path = parsed.path.rstrip("/")
        if not re.search(r"/\d+$", path):
            path = f"{path}/{int(max_side)}"
        else:
            path = re.sub(r"/\d+$", f"/{int(max_side)}", path)
        return urlunparse(parsed._replace(path=path))

    if parsed.path.rstrip("/").endswith("/ids/deliveryService"):
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if "id" in query:
            query["max"] = str(int(max_side))
            return urlunparse(parsed._replace(query=urlencode(query)))

    return media_url


def _media_resource_map(media: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for resource in media.get("resources") or []:
        if not isinstance(resource, Mapping):
            continue
        label = (clean_text(resource.get("label")) or "").casefold()
        url = clean_text(resource.get("url"))
        if "source_width" not in output and resource.get("width") is not None:
            output["source_width"] = resource.get("width")
        if "source_height" not in output and resource.get("height") is not None:
            output["source_height"] = resource.get("height")
        if label == "high-resolution jpeg":
            output["highres_jpeg_url"] = url
        elif label == "screen image":
            output["screen_url"] = url
        elif label == "thumbnail image":
            output["thumbnail_resource_url"] = url
    return output


def canonical_candidate(
    record: Mapping[str, Any], media: Mapping[str, Any], max_side: int = 512
) -> dict[str, Any]:
    """Flatten one Smithsonian object+media pair into the Phase 1 candidate schema."""
    dnr = descriptive(record)
    title_obj = dnr.get("title") or {}
    title = clean_text(title_obj.get("content")) or clean_text(record.get("title"))

    descriptions = _freetext_values(record, "notes", ["description", "summary"])

    object_types = _structured_values(record, "object_type") or _freetext_values(
        record, "objectType"
    )
    creators = _freetext_values(
        record,
        "name",
        ["artist", "maker", "manufacturer", "creator", "designer", "author", "photographer"],
    )
    related_names = _freetext_values(record, "name")

    dates = _freetext_values(record, "date") or _structured_values(record, "date")
    places = _structured_values(record, "place") or _freetext_values(record, "place")
    topics = _structured_values(record, "topic")
    cultures = _structured_values(record, "culture")
    collections = _freetext_values(record, "setName", ["see more items in", "collection"])
    usage_flags = _structured_values(record, "usage_flag")
    object_rights = _freetext_values(record, "objectRights")
    indexed_media_rights = _structured_values(record, "online_media_rights")
    scientific_names = _structured_values(record, "scientific_name") or _freetext_values(
        record, "taxonomicName"
    )
    physical_descriptions = _freetext_values(
        record, "physicalDescription", ["physical description", "medium"]
    )
    credit_lines = _freetext_values(record, "creditLine")

    media_url = clean_text(media.get("content"))
    object_id = clean_text(dnr.get("record_ID")) or clean_text(record.get("url")) or clean_text(
        record.get("id")
    )
    media_id = clean_text(media.get("id")) or clean_text(media.get("idsId")) or clean_text(
        media.get("guid")
    )

    row: dict[str, Any] = {
        "object_id": object_id,
        "edan_id": clean_text(record.get("id")),
        "media_id": media_id,
        "ids_id": clean_text(media.get("idsId")),
        "unit_code": clean_text(dnr.get("unit_code")) or clean_text(record.get("unitCode")),
        "title": title,
        "description": _join(descriptions),
        "object_type": _join(object_types),
        "institution": clean_text(dnr.get("data_source")),
        "collection": _join(collections),
        "creator": _join(creators),
        "related_names": _join(related_names),
        "date": _join(dates),
        "place": _join(places),
        "topics": _join(topics),
        "culture": _join(cultures),
        "scientific_name": _join(scientific_names),
        "physical_description": _join(physical_descriptions),
        "credit_line": _join(credit_lines),
        "usage_flags": _join(usage_flags),
        "source_url": clean_text(dnr.get("record_link")) or clean_text(dnr.get("guid")),
        "record_guid": clean_text(dnr.get("guid")),
        "media_guid": clean_text(media.get("guid")),
        "media_url": media_url,
        "image_url": preferred_ids_derivative_url(media_url, max_side=max_side),
        "thumbnail_url": clean_text(media.get("thumbnail")),
        "media_type": clean_text(media.get("type")),
        "media_rights": clean_text((media.get("usage") or {}).get("access")),
        "metadata_rights": clean_text((dnr.get("metadata_usage") or {}).get("access")),
        "object_rights": _join(object_rights),
        "indexed_media_rights": _join(indexed_media_rights),
        "media_caption": clean_text(media.get("caption")),
        "alt_text": clean_text(media.get("altTextAccessibility")),
        "media_description": clean_text(media.get("extDescrAccessibility")),
        "record_type": clean_text(record.get("type")),
        "record_hash": clean_text(record.get("hash")),
        "record_timestamp": _int_or_none(record.get("timestamp")),
        "record_last_updated": _int_or_none(record.get("lastTimeUpdated")),
        "raw_category": _join(usage_flags),
        "highres_jpeg_url": None,
        "screen_url": None,
        "thumbnail_resource_url": None,
        "source_width": None,
        "source_height": None,
    }
    row.update(_media_resource_map(media))
    row["source_width"] = _int_or_none(row.get("source_width"))
    row["source_height"] = _int_or_none(row.get("source_height"))
    return row


def iter_canonical_candidates(
    record: Mapping[str, Any], *, cc0_only: bool = True, max_side: int = 512
) -> Iterator[dict[str, Any]]:
    if cc0_only and not record_metadata_is_cc0(record):
        return
    for media in iter_media(record):
        if media.get("type") != "Images":
            continue
        if cc0_only and not media_is_cc0_image(media):
            continue
        yield canonical_candidate(record, media, max_side=max_side)
