from dataclasses import replace
import hashlib
import json

import pytest

from examples.custom_plugins import build_config, build_registries
from roast.core.config import RunSpec
from roast.core.config import ArtifactSpec
from roast.execution.orchestrator import PluginRegistries, run_suite
from roast.execution.persistence import FileSystemRunStore
from roast.execution import persistence as persistence_module


def _parse_jsonl_without_roast(path):
    return [
        json.loads(line)
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    ]


def test_file_store_persists_portable_layout_and_resumes(tmp_path) -> None:
    store = FileSystemRunStore(tmp_path)
    config = replace(
        build_config(str(tmp_path)),
        run=RunSpec(
            run_name="portable",
            primary_metric="absolute_error",
            resume_enabled=True,
        ),
    )
    first = run_suite(
        config,
        PluginRegistries(*build_registries()),
        resume_store=store,
    )
    run_directory = tmp_path / "runs" / first.run_id
    expected = {
        "checkpoint.json", "config.json", "errors.jsonl", "items.jsonl",
        "manifest.json", "records/metrics.jsonl", "records/predictions.jsonl",
        "records/runs.jsonl", "run_metadata.json",
    }
    actual = {
        path.relative_to(run_directory).as_posix()
        for path in run_directory.rglob("*") if path.is_file()
    }
    assert actual == expected
    metadata = json.loads((run_directory / "run_metadata.json").read_text("utf-8"))
    assert metadata["schema_version"] == 1
    assert metadata["state"] == "completed"
    assert metadata["counts"] == {
        "errors": 0, "items": 3, "metrics": 3, "predictions": 3, "runs": 3,
    }
    manifest = json.loads((run_directory / "manifest.json").read_text("utf-8"))
    for entry in manifest["files"]:
        content = (run_directory / entry["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]

    # Simulate a third-party tool that knows only the documented JSON contract.
    config_document = json.loads((run_directory / "config.json").read_text("utf-8"))
    assert config_document["schema_version"] == 1
    assert config_document["task_kind"] == "example.numeric_prediction"
    required_fields = {
        "items.jsonl": {"schema_version", "item_id", "dataset_id", "payload"},
        "records/runs.jsonl": {
            "schema_version", "record_id", "run_id", "dataset_id", "model_id",
            "item_id", "status",
        },
        "records/predictions.jsonl": {
            "schema_version", "record_id", "run_id", "dataset_id", "model_id",
            "item_id", "prediction",
        },
        "records/metrics.jsonl": {
            "schema_version", "record_id", "run_id", "dataset_id", "model_id",
            "item_id", "metric_id", "value",
        },
    }
    for relative_path, fields in required_fields.items():
        rows = _parse_jsonl_without_roast(run_directory / relative_path)
        assert rows
        assert all(row["schema_version"] == 1 for row in rows)
        assert all(fields <= row.keys() for row in rows)

    registry_rows = _parse_jsonl_without_roast(
        tmp_path / "_registry" / "run_registry.jsonl"
    )
    assert len(registry_rows) == 1
    assert registry_rows[0]["run_id"] == first.run_id
    assert registry_rows[0]["schema_version"] == 1

    resumed = run_suite(
        replace(config, run=replace(config.run, resume_run_id=first.run_id)),
        PluginRegistries(*build_registries()),
        resume_store=store,
    )
    assert resumed.run_id == first.run_id
    assert resumed.runs == first.runs
    assert resumed.predictions == first.predictions
    assert resumed.metrics == first.metrics
    assert store.list_runs()[0]["run_id"] == first.run_id
    assert len(store.list_runs()) == 1


def test_file_store_rejects_non_file_uri_and_unsafe_run_id(tmp_path) -> None:
    try:
        FileSystemRunStore("s3://bucket/runs")
    except ValueError as error:
        assert "file://" in str(error)
    else:
        raise AssertionError("non-file URI was accepted")

    store = FileSystemRunStore(tmp_path)
    for run_id in ("", "..", "parent/child", "parent\\child"):
        try:
            store.run_directory(run_id)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe run id was accepted: {run_id!r}")


def test_file_store_accepts_artifact_spec_with_a_local_path(tmp_path) -> None:
    store = FileSystemRunStore.from_artifact_spec(ArtifactSpec(str(tmp_path)))
    assert store.root == tmp_path.resolve()


def test_file_store_writes_optional_parquet_alongside_jsonl(tmp_path) -> None:
    parquet = pytest.importorskip("pyarrow.parquet")
    artifact_spec = ArtifactSpec(str(tmp_path), options={"parquet": True})
    store = FileSystemRunStore.from_artifact_spec(artifact_spec)
    config = replace(
        build_config(str(tmp_path)),
        artifacts=artifact_spec,
        run=RunSpec(
            run_name="portable-parquet",
            primary_metric="absolute_error",
            resume_enabled=True,
        ),
    )

    result = run_suite(
        config,
        PluginRegistries(*build_registries()),
        resume_store=store,
    )
    run_directory = store.run_directory(result.run_id)
    parquet_paths = {
        "items.parquet",
        "records/runs.parquet",
        "records/predictions.parquet",
        "records/metrics.parquet",
        "errors.parquet",
    }
    assert all((run_directory / path).is_file() for path in parquet_paths)
    assert (tmp_path / "_registry" / "run_registry.parquet").is_file()
    assert (run_directory / "records/metrics.jsonl").is_file()

    table = parquet.read_table(run_directory / "records" / "metrics.parquet")
    assert table.num_rows == 3
    assert table.schema.metadata[b"roast.schema_version"] == b"1"
    assert json.loads(table.schema.metadata[b"roast.json_columns"]) == [
        "coordinates",
        "metadata",
    ]
    assert json.loads(table.column("metadata")[0].as_py())["direction"] == "minimize"

    manifest = json.loads((run_directory / "manifest.json").read_text("utf-8"))
    manifest_entries = {entry["path"]: entry for entry in manifest["files"]}
    for path in parquet_paths:
        assert manifest_entries[path]["media_type"] == "application/vnd.apache.parquet"
        content = (run_directory / path).read_bytes()
        assert hashlib.sha256(content).hexdigest() == manifest_entries[path]["sha256"]


def test_parquet_dependency_is_lazy_and_has_an_actionable_error(
    tmp_path,
    monkeypatch,
) -> None:
    result = run_suite(
        build_config(str(tmp_path)),
        PluginRegistries(*build_registries()),
    )
    original_import = persistence_module.import_module

    def import_without_pyarrow(name):
        if name == "pyarrow" or name.startswith("pyarrow."):
            error = ModuleNotFoundError("No module named 'pyarrow'")
            error.name = "pyarrow"
            raise error
        return original_import(name)

    monkeypatch.setattr(persistence_module, "import_module", import_without_pyarrow)

    FileSystemRunStore(tmp_path / "json-only").persist_result(result)
    with pytest.raises(RuntimeError, match=r"install ROAST.*parquet.*extra"):
        FileSystemRunStore(tmp_path / "with-parquet", parquet=True).persist_result(result)


def test_artifact_spec_rejects_non_boolean_parquet_option(tmp_path) -> None:
    with pytest.raises(ValueError, match="options.parquet must be a boolean"):
        FileSystemRunStore.from_artifact_spec(
            ArtifactSpec(str(tmp_path), options={"parquet": "yes"})
        )
