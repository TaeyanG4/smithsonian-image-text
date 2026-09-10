import pytest

from smithsonian_image_text.discovery import (
    deterministic_shard_order,
    effective_unit_caps,
    normalize_units,
)
from smithsonian_image_text.schema import (
    iter_canonical_candidates,
    preferred_ids_derivative_url,
)


def test_ids_query_derivative():
    source = "https://ids.si.edu/ids/deliveryService?id=ABC-123"
    assert preferred_ids_derivative_url(source, 512) == (
        "https://ids.si.edu/ids/deliveryService?id=ABC-123&max=512"
    )


def test_ids_query_derivative_replaces_existing_max():
    source = "https://ids.si.edu/ids/deliveryService?id=ABC-123&max=2000"
    assert preferred_ids_derivative_url(source, 512) == (
        "https://ids.si.edu/ids/deliveryService?id=ABC-123&max=512"
    )


def test_ids_ark_derivative():
    source = "https://ids.si.edu/ids/deliveryService/id/ark:/65665/m3abc"
    assert preferred_ids_derivative_url(source, 512) == source + "/512"


def test_ids_ark_derivative_replaces_existing_size():
    source = "https://ids.si.edu/ids/deliveryService/id/ark:/65665/m3abc/1024"
    assert preferred_ids_derivative_url(source, 512) == (
        "https://ids.si.edu/ids/deliveryService/id/ark:/65665/m3abc/512"
    )


def test_non_ids_url_is_preserved():
    source = "https://example.org/image.jpg"
    assert preferred_ids_derivative_url(source, 512) == source


def test_shard_order_is_deterministic():
    urls = [f"https://example.org/{x:02x}.txt" for x in range(16)]
    first = deterministic_shard_order(urls, seed="v1", unit_code="NMAH")
    second = deterministic_shard_order(urls, seed="v1", unit_code="NMAH")
    assert first == second
    assert sorted(first) == sorted(urls)


def test_normalize_units_deduplicates_and_preserves_order():
    assert normalize_units(["nmah", "NASM", "NMAH"], ["NMAH", "NASM"]) == ["NMAH", "NASM"]


def test_normalize_units_rejects_unknown_unit():
    with pytest.raises(ValueError, match="UNKNOWN"):
        normalize_units(["NMAH", "UNKNOWN"], ["NMAH"])


def test_effective_unit_caps_respects_cli_global_cap():
    caps = effective_unit_caps(
        ["NMAH", "FSG"], max_per_unit=50, configured_caps={"NMAH": 10_000, "FSG": 20}
    )
    assert caps == {"NMAH": 50, "FSG": 20}


def test_effective_unit_caps_rejects_nonpositive_values():
    with pytest.raises(ValueError, match="positive"):
        effective_unit_caps(["NMAH"], max_per_unit=0)
    with pytest.raises(ValueError, match="NMAH"):
        effective_unit_caps(["NMAH"], max_per_unit=50, configured_caps={"NMAH": 0})


def test_canonical_candidate_requires_media_level_cc0():
    record = {
        "id": "edan-1",
        "unitCode": "NASM",
        "title": "Test object",
        "type": "edanmdm",
        "content": {
            "freetext": {
                "objectType": [{"label": "Type", "content": "Instrument"}],
                "notes": [{"label": "Summary", "content": "A documented test object."}],
            },
            "indexedStructured": {"topic": ["Science"]},
            "descriptiveNonRepeating": {
                "record_ID": "nasm_test_1",
                "unit_code": "NASM",
                "data_source": "National Air and Space Museum",
                "record_link": "https://example.org/object/1",
                "title": {"content": "Test object"},
                "metadata_usage": {"access": "CC0"},
                "online_media": {
                    "media": [
                        {
                            "id": "media:open",
                            "type": "Images",
                            "usage": {"access": "CC0"},
                            "content": "https://ids.si.edu/ids/deliveryService?id=OPEN",
                            "caption": "Official Smithsonian media caption",
                        },
                        {
                            "id": "media:closed",
                            "type": "Images",
                            "usage": {"access": "Usage conditions apply"},
                            "content": "https://ids.si.edu/ids/deliveryService?id=CLOSED",
                        },
                    ]
                },
            },
        },
    }
    rows = list(iter_canonical_candidates(record, cc0_only=True))
    assert len(rows) == 1
    assert rows[0]["media_id"] == "media:open"
    assert rows[0]["metadata_rights"] == "CC0"
    assert rows[0]["media_rights"] == "CC0"
    assert rows[0]["media_caption"] == "Official Smithsonian media caption"


def test_non_creator_related_name_is_not_mislabeled_creator():
    record = {
        "id": "edan-name-test",
        "unitCode": "NMAH",
        "content": {
            "freetext": {
                "name": [{"label": "depicted", "content": "Example Person"}],
                "objectType": [{"label": "Object Name", "content": "Print"}],
            },
            "descriptiveNonRepeating": {
                "record_ID": "nmah_name_test",
                "title": {"content": "Example print"},
                "record_link": "https://example.org/object/name-test",
                "metadata_usage": {"access": "CC0"},
                "online_media": {
                    "media": [
                        {
                            "id": "media:name-test",
                            "type": "Images",
                            "usage": {"access": "CC0"},
                            "content": "https://ids.si.edu/ids/deliveryService?id=NAME-TEST",
                        }
                    ]
                },
            },
        },
    }
    row = next(iter_canonical_candidates(record, cc0_only=True))
    assert row["creator"] is None
    assert row["related_names"] == "Example Person"


def test_non_cc0_record_metadata_blocks_even_cc0_image_media():
    record = {
        "id": "edan-2",
        "unitCode": "NMAH",
        "content": {
            "descriptiveNonRepeating": {
                "record_ID": "nmah_test_2",
                "metadata_usage": {"access": "Usage conditions apply"},
                "online_media": {
                    "media": [
                        {
                            "id": "media:open",
                            "type": "Images",
                            "usage": {"access": "CC0"},
                            "content": "https://ids.si.edu/ids/deliveryService?id=OPEN",
                        }
                    ]
                },
            }
        },
    }
    assert list(iter_canonical_candidates(record, cc0_only=True)) == []
