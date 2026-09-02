from __future__ import annotations

import json

import pytest

from examples.custom_plugins import build_config
from roast.core.config import BenchmarkSuiteConfig, PluginSpec, RunSpec
from roast.core.events import Availability, ProgressEvent
from roast.core.records import (
    ArtifactManifest,
    ArtifactRecord,
    BenchmarkResult,
    ItemRecord,
    MetricRecord,
    PredictionRecord,
    RunRecord,
)
from roast.core.schema import SCHEMA_VERSION, SchemaError
from roast.core.status import RunStatus
from roast.serialization.json import dumps


def build_result() -> BenchmarkResult:
    config = build_config()
    item = ItemRecord(item_id="number-0", dataset_id="tiny", payload=1, target=2)
    run = RunRecord(
        record_id="run:tiny:double:number-0",
        run_id="contract-fixture",
        dataset_id="tiny",
        model_id="double",
        item_id="number-0",
        status=RunStatus.SUCCESS,
    )
    prediction = PredictionRecord(
        record_id="prediction:tiny:double:number-0",
        run_id="contract-fixture",
        dataset_id="tiny",
        model_id="double",
        item_id="number-0",
        prediction=2,
        truth=2,
    )
    metric = MetricRecord(
        record_id="metric:tiny:double:number-0:absolute_error",
        run_id="contract-fixture",
        dataset_id="tiny",
        model_id="double",
        item_id="number-0",
        metric_id="absolute_error",
        value=0.0,
    )
    manifest = ArtifactManifest(
        run_id="contract-fixture",
        artifacts=(
            ArtifactRecord(
                artifact_id="config",
                kind="config",
                uri="memory://contract-fixture/config.json",
                media_type="application/json",
            ),
        ),
    )
    return BenchmarkResult(
        run_id="contract-fixture",
        task_kind=config.task_kind,
        config=config,
        items=(item,),
        runs=(run,),
        predictions=(prediction,),
        metrics=(metric,),
        artifact_manifest=manifest,
    )


def test_config_is_versioned_and_json_round_trips() -> None:
    config = build_config()

    payload = json.loads(dumps(config))
    restored = BenchmarkSuiteConfig.from_dict(payload)

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["datasets"][0]["provider"]["schema_version"] == SCHEMA_VERSION
    assert payload["artifacts"]["output_uri"] == "benchmark-results"
    assert restored == config


def test_result_records_and_manifest_are_versioned_and_round_trip() -> None:
    result = build_result()

    payload = json.loads(dumps(result))
    restored = BenchmarkResult.from_dict(payload)

    assert restored == result
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["items"][0]["schema_version"] == SCHEMA_VERSION
    assert payload["runs"][0]["schema_version"] == SCHEMA_VERSION
    assert payload["predictions"][0]["schema_version"] == SCHEMA_VERSION
    assert payload["metrics"][0]["schema_version"] == SCHEMA_VERSION
    assert payload["artifact_manifest"]["schema_version"] == SCHEMA_VERSION


def test_events_and_availability_are_versioned() -> None:
    event = ProgressEvent(kind="item_started", current=1, total=3)
    availability = Availability(available=False, reason="optional dependency is missing")

    assert ProgressEvent.from_dict(event.to_dict()) == event
    assert Availability.from_dict(availability.to_dict()) == availability
    assert event.to_dict()["schema_version"] == SCHEMA_VERSION

    missing_available = availability.to_dict()
    missing_available.pop("available")
    with pytest.raises(SchemaError, match="available is required"):
        Availability.from_dict(missing_available)


def test_unknown_missing_and_non_integer_schema_versions_are_rejected() -> None:
    payload = build_config().to_dict()
    payload["schema_version"] = 999
    with pytest.raises(SchemaError, match="schema_version"):
        BenchmarkSuiteConfig.from_dict(payload)

    payload = build_config().to_dict()
    payload.pop("schema_version")
    with pytest.raises(SchemaError, match="schema_version is required"):
        BenchmarkSuiteConfig.from_dict(payload)

    payload["schema_version"] = "1"
    with pytest.raises(SchemaError, match="schema_version"):
        BenchmarkSuiteConfig.from_dict(payload)


def test_deserialization_does_not_coerce_boolean_strings() -> None:
    payload = RunSpec().to_dict()
    payload["resume_enabled"] = "false"

    with pytest.raises(SchemaError, match="must be a boolean"):
        RunSpec.from_dict(payload)


def test_config_json_objects_are_defensively_copied_and_typed_readonly() -> None:
    source = {"nested": {"values": [1, 2]}}
    spec = PluginSpec("example", source)
    source["nested"]["values"].append(3)

    assert spec.options == {"nested": {"values": (1, 2)}}
    assert json.loads(dumps(spec))["options"]["nested"]["values"] == [1, 2]
    with pytest.raises(TypeError):
        spec.options["new"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        spec.options["nested"]["new"] = True  # type: ignore[index,union-attr]


def test_run_status_must_be_an_enum_instance() -> None:
    with pytest.raises(SchemaError, match="RunStatus"):
        MetricRecord(
            record_id="metric",
            run_id="run",
            dataset_id="dataset",
            model_id="model",
            item_id="item",
            metric_id="quality",
            value=1.0,
            status="success",  # type: ignore[arg-type]
        )


def test_metric_record_normalizes_numbers_and_rejects_other_json_values() -> None:
    common = {
        "record_id": "metric",
        "run_id": "run",
        "dataset_id": "dataset",
        "model_id": "model",
        "item_id": "item",
        "metric_id": "quality",
    }

    integer_metric = MetricRecord(**common, value=1)
    assert integer_metric.value == 1.0
    assert type(integer_metric.value) is float

    for invalid in (True, "1", [1], {"value": 1}):
        with pytest.raises(SchemaError, match="number or null"):
            MetricRecord(**common, value=invalid)  # type: ignore[arg-type]

    with pytest.raises(SchemaError, match="finite"):
        MetricRecord(**common, value=float("nan"))


def test_record_json_values_are_defensively_copied_and_deeply_readonly() -> None:
    payload = {"values": [1, 2]}
    target = [2, 4]
    metadata = {"labels": ["source"]}
    coordinates = {"indices": [0, 1]}

    item = ItemRecord(
        item_id="item",
        dataset_id="dataset",
        payload=payload,
        target=target,
        metadata=metadata,
    )
    prediction = PredictionRecord(
        record_id="prediction",
        run_id="run",
        dataset_id="dataset",
        model_id="model",
        item_id="item",
        prediction=target,
        coordinates=coordinates,
        metadata=metadata,
    )
    metric = MetricRecord(
        record_id="metric",
        run_id="run",
        dataset_id="dataset",
        model_id="model",
        item_id="item",
        metric_id="quality",
        value=1.0,
        coordinates=coordinates,
        metadata=metadata,
    )
    artifact = ArtifactRecord(
        artifact_id="artifact",
        kind="record",
        uri="memory://artifact",
        media_type="application/json",
        metadata=metadata,
    )

    payload["values"].append(3)
    target.append(6)
    metadata["labels"].append("changed")
    coordinates["indices"].append(2)

    assert item.payload == {"values": (1, 2)}
    assert item.target == (2, 4)
    assert item.metadata == {"labels": ("source",)}
    assert prediction.prediction == (2, 4)
    assert prediction.coordinates == {"indices": (0, 1)}
    assert metric.metadata == {"labels": ("source",)}
    assert artifact.metadata == {"labels": ("source",)}

    with pytest.raises(TypeError):
        item.payload["changed"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        item.metadata["labels"][0] = "changed"  # type: ignore[index]


def test_non_json_options_and_non_finite_values_are_rejected() -> None:
    with pytest.raises(SchemaError, match="non-JSON"):
        PluginSpec("bad", {"value": object()})  # type: ignore[dict-item]
    with pytest.raises(SchemaError, match="finite"):
        PluginSpec("bad", {"value": float("nan")})
    with pytest.raises(SchemaError, match="non-string key"):
        dumps({1: "value"})  # type: ignore[dict-item]
