from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_yaml(name: str):
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


def test_phase0_release_hard_limits_are_frozen():
    project = load_yaml("collection.yaml")["project"]
    assert 20_000 <= int(project["min_final_images"]) <= int(project["target_final_images"])
    assert int(project["target_final_images"]) <= 25_000
    assert int(project["starter_images"]) == 5_000
    assert int(project["max_side_px"]) <= 512
    assert float(project["target_package_gb"]) <= 4.0
    assert float(project["hard_cap_gb"]) <= 5.0
    assert float(project["target_package_gb"]) <= float(project["hard_cap_gb"])
    assert float(project["rebuild_target_hours"]) <= 8.0


def test_phase2_candidate_pool_bounds_are_frozen():
    discovery = load_yaml("collection.yaml")["metadata_discovery"]
    assert int(discovery["min_candidates"]) == 50_000
    assert int(discovery["min_candidates"]) <= int(discovery["target_candidates"])
    assert int(discovery["target_candidates"]) <= int(discovery["max_candidates"])
    assert int(discovery["max_candidates"]) == 100_000
    assert set(discovery["smoke_units"]).issubset(set(discovery["preferred_units"]))


def test_automatic_rights_gate_accepts_only_cc0_images():
    rights = load_yaml("eligibility_rules.yaml")["rights"]
    assert set(rights["accepted_metadata_access"]) == {"CC0"}
    assert set(rights["accepted_media_access"]) == {"CC0"}
    assert set(rights["accepted_media_types"]) == {"Images"}
