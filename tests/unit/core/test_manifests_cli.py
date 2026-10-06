from dataclasses import replace
import json

import pytest

from examples.custom_plugins import build_config
from roast.cli import main
from roast.manifests import (
    MANIFEST_FORMAT,
    SuiteManifest,
    load_manifest,
)
from roast.plugins.errors import ManifestError
from roast.plugins.registry import PresetRegistry


def test_inline_json_and_yaml_manifests_resolve(tmp_path) -> None:
    manifest = SuiteManifest(suite=build_config())
    json_path = tmp_path / "suite.json"
    json_path.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
    assert load_manifest(json_path) == build_config()

    yaml = pytest.importorskip("yaml")
    yaml_path = tmp_path / "suite.yaml"
    yaml_path.write_text(yaml.safe_dump(manifest.to_dict()), encoding="utf-8")
    assert load_manifest(yaml_path) == build_config()


def test_preset_manifest_resolves_consumer_factory(tmp_path) -> None:
    presets = PresetRegistry()
    presets.register(
        "consumer.tiny",
        lambda options: build_config(str(options.get("output_uri", "results"))),
    )
    path = tmp_path / "preset.json"
    path.write_text(json.dumps({
        "format": MANIFEST_FORMAT,
        "schema_version": 1,
        "preset": "consumer.tiny",
        "preset_options": {"output_uri": "chosen"},
    }), encoding="utf-8")
    assert load_manifest(path, presets).artifacts.output_uri == "chosen"


def test_preset_manifest_applies_recursive_overrides(tmp_path) -> None:
    presets = PresetRegistry()
    presets.register("consumer.tiny", lambda options: build_config())
    path = tmp_path / "composed-preset.json"
    path.write_text(json.dumps({
        "format": MANIFEST_FORMAT,
        "schema_version": 1,
        "preset": "consumer.tiny",
        "preset_options": {},
        "overrides": {
            "artifacts": {"output_uri": "composed-results", "persist": True},
            "run": {"run_name": "nightly", "random_seed": 42},
        },
    }), encoding="utf-8")

    config = load_manifest(path, presets)

    assert config.artifacts.output_uri == "composed-results"
    assert config.artifacts.persist is True
    assert config.artifacts.options == {}
    assert config.run.run_name == "nightly"
    assert config.run.random_seed == 42
    assert config.run.primary_metric == "absolute_error"
    assert config.datasets == build_config().datasets


def test_manifest_validation_is_actionable() -> None:
    with pytest.raises(ManifestError, match="exactly one"):
        SuiteManifest()
    with pytest.raises(ManifestError, match="Unsupported manifest format"):
        SuiteManifest(suite=build_config(), format="old@1")
    with pytest.raises(ManifestError, match="Unknown manifest fields"):
        SuiteManifest.from_dict({
            "format": MANIFEST_FORMAT,
            "schema_version": 1,
            "suite": build_config().to_dict(),
            "typo": True,
        })


def test_cli_lists_plugins_resolves_and_runs_manifest(tmp_path, capsys) -> None:
    output_root = tmp_path / "artifacts"
    config = replace(
        build_config(str(output_root)),
        artifacts=replace(build_config().artifacts, output_uri=str(output_root), persist=True),
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(SuiteManifest(suite=config).to_dict()), encoding="utf-8")

    assert main(["plugins", "list", "--plugin", "examples.custom_plugins"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["datasets"] == ["example.inline_numbers"]

    assert main(["resolve-manifest", "--manifest", str(path), "--plugin", "examples.custom_plugins"]) == 0
    resolved = json.loads(capsys.readouterr().out)
    assert resolved["task_kind"] == "example.numeric_prediction"

    assert main(["run", "--manifest", str(path), "--plugin", "examples.custom_plugins"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["runs"]) == 3
    assert (output_root / "runs" / result["run_id"] / "manifest.json").is_file()
