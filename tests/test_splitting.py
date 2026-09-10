from smithsonian_image_text.splitting import assign_object_splits


def test_object_split_is_leakage_safe_and_deterministic():
    rows = [
        {"object_id": "a", "category_code": "art"},
        {"object_id": "a", "category_code": "art"},
        {"object_id": "b", "category_code": "art"},
        {"object_id": "c", "category_code": "science"},
        {"object_id": "d", "category_code": "science"},
        {"object_id": "e", "category_code": "science"},
    ]
    first = assign_object_splits(rows, seed="test")
    second = assign_object_splits(rows, seed="test")
    assert first == second
    assert set(first) == {"a", "b", "c", "d", "e"}
    assert first["a"] in {"train", "validation", "test"}


def test_split_ratios_validate():
    rows = [{"object_id": "a", "category_code": "art"}]
    try:
        assign_object_splits(rows, seed="test", ratios={"train": 0.9, "validation": 0.1, "test": 0.1})
    except ValueError as exc:
        assert "sum to 1" in str(exc)
    else:
        raise AssertionError("invalid split ratios should fail")
