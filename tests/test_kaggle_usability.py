from scripts.kaggle_usability import (
    UPDATE_DATABUNDLE_METADATA_EXTERNAL,
    build_browser_script,
)


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
