from smithsonian_image_text.captions import TEXT_SOURCE, build_model_text


def test_model_text_is_deterministic_source_only_composition():
    row = {
        "title": "Apollo 11 Command Module",
        "object_type": "Spacecraft",
        "date": "1969",
        "place": "United States",
    }
    assert build_model_text(row) == (
        "Apollo 11 Command Module. Object type: Spacecraft. Date: 1969. "
        "Place: United States."
    )
    assert TEXT_SOURCE == "smithsonian_metadata_composed"


def test_model_text_omits_missing_and_duplicate_values():
    row = {"title": "Bowl", "object_type": "Bowl", "date": None, "topics": "Ceramics"}
    assert build_model_text(row) == "Bowl. Topics: Ceramics."


def test_model_text_caps_long_description_without_losing_source_field_order():
    row = {
        "title": "Aircraft",
        "object_type": "Vehicle",
        "description": "historical description " * 100,
    }
    text = build_model_text(row)
    assert len(text) <= 512
    assert text.startswith("Aircraft. Object type: Vehicle. Description:")
    assert "…" in text
