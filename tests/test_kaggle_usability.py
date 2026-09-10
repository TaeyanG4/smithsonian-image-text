import json
from pathlib import Path
from tempfile import TemporaryDirectory

import scripts.kaggle_usability as ku
from scripts.kaggle_usability import UPDATE_DATABUNDLE_METADATA_EXTERNAL, build_browser_script


def test_browser_script_uses_same_origin_without_exporting_credentials() -> None:
    plan = [
        {
            "verificationInfo": {"datasetId": 1, "databundleVersionId": 2},
            "firestorePath": "versions/example/files/file.csv",
            "description": "File description",
            "columns": [],
        }
    ]

    script = build_browser_script(plan)

    assert UPDATE_DATABUNDLE_METADATA_EXTERNAL in script
    assert "credentials:'same-origin'" in script
    assert "X-XSRF-TOKEN" in script
    assert "X-Kaggle-Build-Version" in script
    assert "Authorization" not in script
    assert "document.cookie=" not in script
    assert "File description" in script


def test_browser_script_does_not_log_cookie_values() -> None:
    script = build_browser_script([])

    assert "console.log(xsrf" not in script
    assert "console.log(cookieValue" not in script


def test_select_metadata_path_matches_live_top_level_resources(monkeypatch) -> None:
    with TemporaryDirectory(dir=ku.ROOT / "tmp_research") as temp_dir:
        release_root = Path(temp_dir)
        old_release = release_root / "museum-images"
        new_release = release_root / "museum-images-v3-final"
        old_release.mkdir()
        new_release.mkdir()
        (old_release / "dataset-metadata.json").write_text(
            json.dumps({"resources": [{"path": "README.md"}, {"path": "legacy.csv"}]}),
            encoding="utf-8",
        )
        expected = new_release / "dataset-metadata.json"
        expected.write_text(
            json.dumps({"resources": [{"path": "README.md"}, {"path": "metadata.parquet"}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(ku, "RELEASE_ROOT", release_root)
        context = ku.LiveContext(
            dataset_id=1,
            dataset_version_id=2,
            databundle_version_id=3,
            version_number=3,
            root_firestore_path="root",
            file_firestore_paths={"README.md": "r", "metadata.parquet": "m"},
        )

        assert ku.select_metadata_path(context) == expected
