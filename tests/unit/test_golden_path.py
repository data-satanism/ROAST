import hashlib
import json

from roast import (
    FileSystemRunStore,
    PluginRegistries,
    build_leaderboard,
    load_artifact_root,
    run_suite,
)
from examples.toy_plugins import build_registries, classification_config


def test_golden_path_run_persist_reload_and_compare(tmp_path) -> None:
    result = run_suite(
        classification_config(str(tmp_path)),
        PluginRegistries(*build_registries()),
    )
    FileSystemRunStore(tmp_path).persist_result(result)
    loaded = load_artifact_root(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].to_dict() == result.to_dict()
    assert build_leaderboard(loaded[0]) == build_leaderboard(result)


def test_committed_v1_fixture_is_parseable_without_plugin_imports(pytestconfig) -> None:
    fixture_root = pytestconfig.rootpath / "tests" / "fixtures" / "artifact_root_v1"
    result = load_artifact_root(fixture_root)[0]
    assert result.schema_version == 1
    assert result.run_id == "toy-fixture"
    assert build_leaderboard(result) == ({
        "run_id": "toy-fixture",
        "model_id": "majority",
        "metric_id": "accuracy",
        "score": 1.0,
        "direction": "maximize",
        "observations": 1,
        "rank": 1,
    },)
    run_directory = fixture_root / "runs" / "toy-fixture"
    manifest = json.loads((run_directory / "manifest.json").read_text("utf-8"))
    assert manifest["schema_version"] == 1
    for entry in manifest["files"]:
        assert hashlib.sha256((run_directory / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]


def test_core_and_bmf_tests_do_not_import_industrial(pytestconfig) -> None:
    project_root = pytestconfig.rootpath
    for root in (project_root / "roast", project_root / "tests"):
        for path in root.rglob("*.py"):
            text = path.read_text("utf-8").lower()
            forbidden_module = "fedot" + "_ind"
            assert f"import {forbidden_module}" not in text
            assert f"from {forbidden_module}" not in text
