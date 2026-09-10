"""Deterministic object-level train/validation/test split assignment."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


SPLIT_ORDER = ("train", "validation", "test")


def _rank(seed: str, category: str, object_id: str) -> str:
    return hashlib.sha256(f"{seed}:{category}:{object_id}".encode()).hexdigest()


def assign_object_splits(
    rows: Sequence[Mapping[str, Any]],
    *,
    seed: str,
    ratios: Mapping[str, float] | None = None,
) -> dict[str, str]:
    """Assign each object exactly one split while closely matching category row ratios."""
    split_ratios = dict(ratios or {"train": 0.8, "validation": 0.1, "test": 0.1})
    if set(split_ratios) != set(SPLIT_ORDER):
        raise ValueError("ratios must define train, validation, and test")
    if abs(sum(split_ratios.values()) - 1.0) > 1e-9 or any(
        value <= 0 for value in split_ratios.values()
    ):
        raise ValueError("split ratios must be positive and sum to 1")

    rows_by_object: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        object_id = str(row.get("object_id") or "")
        if not object_id:
            raise ValueError("Every row must have object_id")
        rows_by_object[object_id].append(row)

    groups_by_category: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for object_id, object_rows in rows_by_object.items():
        category_counts = Counter(str(row.get("category_code") or "other_objects") for row in object_rows)
        primary_category = sorted(category_counts, key=lambda key: (-category_counts[key], key))[0]
        groups_by_category[primary_category].append((object_id, len(object_rows)))

    assignments: dict[str, str] = {}
    for category, groups in groups_by_category.items():
        groups.sort(key=lambda item: _rank(seed, category, item[0]))
        total_rows = sum(size for _, size in groups)
        target_rows = {split: split_ratios[split] * total_rows for split in SPLIT_ORDER}
        assigned_rows = {split: 0 for split in SPLIT_ORDER}
        for object_id, size in groups:
            deficits = {split: target_rows[split] - assigned_rows[split] for split in SPLIT_ORDER}
            chosen = max(SPLIT_ORDER, key=lambda split: (deficits[split], -SPLIT_ORDER.index(split)))
            assignments[object_id] = chosen
            assigned_rows[chosen] += size
    return assignments
