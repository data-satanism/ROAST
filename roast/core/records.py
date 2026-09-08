from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from roast.core.schema import (
    ReadonlyJSONObject,
    ReadonlyJSONValue,
    SCHEMA_VERSION,
    SchemaError,
    SchemaMixin,
    array_value,
    ensure_json_value,
    ensure_schema_version,
    number_or_none,
    object_value,
    optional_json_value,
    optional_string,
    require_schema_version,
    required_json_value,
    require_string,
    _frozen_json,
    _frozen_object,
    _mapping,
    _name,
)
from roast.core.config import BenchmarkSuiteConfig
from roast.core.status import RunStatus


def _status(data: Mapping[str, Any], *, schema_name: str) -> RunStatus:
    value = require_string(data, "status", schema_name=schema_name)
    try:
        return RunStatus(value)
    except ValueError as error:
        raise SchemaError(f"{schema_name}.status has an unknown value: {value!r}") from error
def _validate_items_and_record_ids(
    items: tuple[ItemRecord, ...],
    runs: tuple[RunRecord, ...],
    predictions: tuple[PredictionRecord, ...],
    metrics: tuple[MetricRecord, ...],
) -> None:
    item_keys: set[tuple[str, str]] = set()
    for item in items:
        key = (item.dataset_id, item.item_id)
        if key in item_keys:
            raise SchemaError(f"Duplicate ItemRecord key: {key!r}")
        item_keys.add(key)

    record_ids: set[str] = set()
    for record in (*runs, *predictions, *metrics):
        if record.record_id in record_ids:
            raise SchemaError(f"Duplicate record_id: {record.record_id!r}")
        record_ids.add(record.record_id)
        if (record.dataset_id, record.item_id) not in item_keys:
            raise SchemaError(
                f"Record {record.record_id!r} references an unknown item "
                f"({record.dataset_id!r}, {record.item_id!r})"
            )


@dataclass(frozen=True)
class ItemRecord(SchemaMixin):
    """Represent one task-defined benchmark work unit.

    Attributes:
        item_id: Identifier unique within a dataset.
        dataset_id: Identifier of the source dataset specification.
        payload: Read-only task-specific JSON input.
        target: Read-only task-specific expected output, when available.
        metadata: Read-only consumer-defined JSON metadata.
        schema_version: Version of the serialized schema.
    """

    item_id: str
    dataset_id: str
    payload: ReadonlyJSONValue
    target: ReadonlyJSONValue = None
    metadata: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ensure_schema_version(self.schema_version, schema_name="ItemRecord")
        _name(self.item_id, "ItemRecord.item_id")
        _name(self.dataset_id, "ItemRecord.dataset_id")
        object.__setattr__(
            self, "payload", _frozen_json(self.payload, path="ItemRecord.payload")
        )
        object.__setattr__(
            self, "target", _frozen_json(self.target, path="ItemRecord.target")
        )
        object.__setattr__(
            self, "metadata", _frozen_object(self.metadata, path="ItemRecord.metadata")
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ItemRecord":
        return cls(
            item_id=require_string(data, "item_id", schema_name="ItemRecord"),
            dataset_id=require_string(data, "dataset_id", schema_name="ItemRecord"),
            payload=required_json_value(data, "payload", schema_name="ItemRecord"),
            target=optional_json_value(data, "target", schema_name="ItemRecord"),
            metadata=object_value(data, "metadata", schema_name="ItemRecord"),
            schema_version=require_schema_version(data, schema_name="ItemRecord"),
        )


@dataclass(frozen=True)
class RunRecord(SchemaMixin):
    """Represent the lifecycle outcome for one item and model pair.

    Attributes:
        record_id: Identifier unique among records in a result.
        run_id: Identifier of the containing benchmark run.
        dataset_id: Identifier of the configured dataset.
        model_id: Identifier of the configured model.
        item_id: Identifier of the evaluated item.
        status: Task-neutral lifecycle status.
        message: Human-readable status details.
        started_at: Optional serialized start timestamp.
        finished_at: Optional serialized finish timestamp.
        metadata: Read-only consumer-defined JSON metadata.
        schema_version: Version of the serialized schema.
    """

    record_id: str
    run_id: str
    dataset_id: str
    model_id: str
    item_id: str
    status: RunStatus
    message: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    metadata: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ensure_schema_version(self.schema_version, schema_name="RunRecord")
        for field_name in ("record_id", "run_id", "dataset_id", "model_id", "item_id"):
            _name(getattr(self, field_name), f"RunRecord.{field_name}")
        if not isinstance(self.status, RunStatus):
            raise SchemaError("RunRecord.status must be a RunStatus")
        if not isinstance(self.message, str):
            raise SchemaError("RunRecord.message must be a string")
        if self.started_at is not None and not isinstance(self.started_at, str):
            raise SchemaError("RunRecord.started_at must be a string or null")
        if self.finished_at is not None and not isinstance(self.finished_at, str):
            raise SchemaError("RunRecord.finished_at must be a string or null")
        object.__setattr__(
            self, "metadata", _frozen_object(self.metadata, path="RunRecord.metadata")
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunRecord":
        return cls(
            record_id=require_string(data, "record_id", schema_name="RunRecord"),
            run_id=require_string(data, "run_id", schema_name="RunRecord"),
            dataset_id=require_string(data, "dataset_id", schema_name="RunRecord"),
            model_id=require_string(data, "model_id", schema_name="RunRecord"),
            item_id=require_string(data, "item_id", schema_name="RunRecord"),
            status=_status(data, schema_name="RunRecord"),
            message=(
                require_string(data, "message", schema_name="RunRecord")
                if "message" in data
                else ""
            ),
            started_at=optional_string(data, "started_at", schema_name="RunRecord"),
            finished_at=optional_string(data, "finished_at", schema_name="RunRecord"),
            metadata=object_value(data, "metadata", schema_name="RunRecord"),
            schema_version=require_schema_version(data, schema_name="RunRecord"),
        )


@dataclass(frozen=True)
class PredictionRecord(SchemaMixin):
    """Represent a model prediction for one benchmark item.

    Attributes:
        record_id: Identifier unique among records in a result.
        run_id: Identifier of the containing benchmark run.
        dataset_id: Identifier of the configured dataset.
        model_id: Identifier of the configured model.
        item_id: Identifier of the evaluated item.
        prediction: Read-only task-specific prediction value.
        truth: Read-only expected value, when available.
        status: Task-neutral lifecycle status.
        coordinates: Read-only coordinates within a structured prediction.
        metadata: Read-only consumer-defined JSON metadata.
        schema_version: Version of the serialized schema.
    """

    record_id: str
    run_id: str
    dataset_id: str
    model_id: str
    item_id: str
    prediction: ReadonlyJSONValue
    truth: ReadonlyJSONValue = None
    status: RunStatus = RunStatus.SUCCESS
    coordinates: ReadonlyJSONObject = field(default_factory=dict)
    metadata: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ensure_schema_version(self.schema_version, schema_name="PredictionRecord")
        for field_name in ("record_id", "run_id", "dataset_id", "model_id", "item_id"):
            _name(getattr(self, field_name), f"PredictionRecord.{field_name}")
        if not isinstance(self.status, RunStatus):
            raise SchemaError("PredictionRecord.status must be a RunStatus")
        object.__setattr__(
            self,
            "prediction",
            _frozen_json(self.prediction, path="PredictionRecord.prediction"),
        )
        object.__setattr__(
            self, "truth", _frozen_json(self.truth, path="PredictionRecord.truth")
        )
        object.__setattr__(
            self,
            "coordinates",
            _frozen_object(self.coordinates, path="PredictionRecord.coordinates"),
        )
        object.__setattr__(
            self,
            "metadata",
            _frozen_object(self.metadata, path="PredictionRecord.metadata"),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PredictionRecord":
        return cls(
            record_id=require_string(data, "record_id", schema_name="PredictionRecord"),
            run_id=require_string(data, "run_id", schema_name="PredictionRecord"),
            dataset_id=require_string(data, "dataset_id", schema_name="PredictionRecord"),
            model_id=require_string(data, "model_id", schema_name="PredictionRecord"),
            item_id=require_string(data, "item_id", schema_name="PredictionRecord"),
            prediction=required_json_value(data, "prediction", schema_name="PredictionRecord"),
            truth=optional_json_value(data, "truth", schema_name="PredictionRecord"),
            status=(
                _status(data, schema_name="PredictionRecord")
                if "status" in data
                else RunStatus.SUCCESS
            ),
            coordinates=object_value(data, "coordinates", schema_name="PredictionRecord"),
            metadata=object_value(data, "metadata", schema_name="PredictionRecord"),
            schema_version=require_schema_version(data, schema_name="PredictionRecord"),
        )


@dataclass(frozen=True)
class MetricRecord(SchemaMixin):
    """Represent one scalar metric value for an evaluated item.

    Attributes:
        record_id: Identifier unique among records in a result.
        run_id: Identifier of the containing benchmark run.
        dataset_id: Identifier of the configured dataset.
        model_id: Identifier of the configured model.
        item_id: Identifier of the evaluated item.
        metric_id: Identifier of the configured metric.
        value: Finite scalar metric value, or ``None`` when unavailable.
        status: Task-neutral lifecycle status.
        coordinates: Read-only coordinates for contextual metric values.
        metadata: Read-only consumer-defined JSON metadata.
        schema_version: Version of the serialized schema.
    """

    record_id: str
    run_id: str
    dataset_id: str
    model_id: str
    item_id: str
    metric_id: str
    value: float | None
    status: RunStatus = RunStatus.SUCCESS
    coordinates: ReadonlyJSONObject = field(default_factory=dict)
    metadata: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ensure_schema_version(self.schema_version, schema_name="MetricRecord")
        for field_name in (
            "record_id",
            "run_id",
            "dataset_id",
            "model_id",
            "item_id",
            "metric_id",
        ):
            _name(getattr(self, field_name), f"MetricRecord.{field_name}")
        if not isinstance(self.status, RunStatus):
            raise SchemaError("MetricRecord.status must be a RunStatus")
        if self.value is None:
            normalized_value = None
        elif isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise SchemaError("MetricRecord.value must be a number or null")
        else:
            normalized_value = float(self.value)
            ensure_json_value(normalized_value, path="MetricRecord.value")
        object.__setattr__(self, "value", normalized_value)
        object.__setattr__(
            self,
            "coordinates",
            _frozen_object(self.coordinates, path="MetricRecord.coordinates"),
        )
        object.__setattr__(
            self, "metadata", _frozen_object(self.metadata, path="MetricRecord.metadata")
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MetricRecord":
        return cls(
            record_id=require_string(data, "record_id", schema_name="MetricRecord"),
            run_id=require_string(data, "run_id", schema_name="MetricRecord"),
            dataset_id=require_string(data, "dataset_id", schema_name="MetricRecord"),
            model_id=require_string(data, "model_id", schema_name="MetricRecord"),
            item_id=require_string(data, "item_id", schema_name="MetricRecord"),
            metric_id=require_string(data, "metric_id", schema_name="MetricRecord"),
            value=number_or_none(data, "value", schema_name="MetricRecord"),
            status=(
                _status(data, schema_name="MetricRecord")
                if "status" in data
                else RunStatus.SUCCESS
            ),
            coordinates=object_value(data, "coordinates", schema_name="MetricRecord"),
            metadata=object_value(data, "metadata", schema_name="MetricRecord"),
            schema_version=require_schema_version(data, schema_name="MetricRecord"),
        )


@dataclass(frozen=True)
class ArtifactRecord(SchemaMixin):
    """Describe one persisted or externally managed artifact.

    Attributes:
        artifact_id: Identifier unique within an artifact manifest.
        kind: Stable consumer-defined artifact kind.
        uri: Portable location of the artifact.
        media_type: Media type of the referenced content.
        checksum: Optional checksum supplied by a persistence layer.
        metadata: Read-only consumer-defined JSON metadata.
        schema_version: Version of the serialized schema.
    """

    artifact_id: str
    kind: str
    uri: str
    media_type: str
    checksum: str | None = None
    metadata: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ensure_schema_version(self.schema_version, schema_name="ArtifactRecord")
        for field_name in ("artifact_id", "kind", "uri", "media_type"):
            _name(getattr(self, field_name), f"ArtifactRecord.{field_name}")
        if self.checksum is not None and not isinstance(self.checksum, str):
            raise SchemaError("ArtifactRecord.checksum must be a string or null")
        object.__setattr__(
            self,
            "metadata",
            _frozen_object(self.metadata, path="ArtifactRecord.metadata"),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactRecord":
        return cls(
            artifact_id=require_string(data, "artifact_id", schema_name="ArtifactRecord"),
            kind=require_string(data, "kind", schema_name="ArtifactRecord"),
            uri=require_string(data, "uri", schema_name="ArtifactRecord"),
            media_type=require_string(data, "media_type", schema_name="ArtifactRecord"),
            checksum=optional_string(data, "checksum", schema_name="ArtifactRecord"),
            metadata=object_value(data, "metadata", schema_name="ArtifactRecord"),
            schema_version=require_schema_version(data, schema_name="ArtifactRecord"),
        )


@dataclass(frozen=True)
class ArtifactManifest(SchemaMixin):
    """Collect artifact references associated with one benchmark run.

    Attributes:
        run_id: Identifier of the associated benchmark run.
        artifacts: Artifact records contained in the manifest.
        metadata: Read-only consumer-defined JSON metadata.
        schema_version: Version of the serialized schema.
    """

    run_id: str
    artifacts: tuple[ArtifactRecord, ...] = ()
    metadata: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ensure_schema_version(self.schema_version, schema_name="ArtifactManifest")
        _name(self.run_id, "ArtifactManifest.run_id")
        artifacts = tuple(self.artifacts)
        if any(not isinstance(record, ArtifactRecord) for record in artifacts):
            raise SchemaError("ArtifactManifest.artifacts must contain ArtifactRecord values")
        artifact_ids = [record.artifact_id for record in artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise SchemaError("Duplicate artifact_id values are not allowed")
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(
            self,
            "metadata",
            _frozen_object(self.metadata, path="ArtifactManifest.metadata"),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactManifest":
        artifacts = array_value(data, "artifacts", schema_name="ArtifactManifest")
        return cls(
            run_id=require_string(data, "run_id", schema_name="ArtifactManifest"),
            artifacts=tuple(
                ArtifactRecord.from_dict(_mapping(item, path="ArtifactManifest.artifacts[]"))
                for item in artifacts
            ),
            metadata=object_value(data, "metadata", schema_name="ArtifactManifest"),
            schema_version=require_schema_version(data, schema_name="ArtifactManifest"),
        )


@dataclass(frozen=True)
class BenchmarkResult(SchemaMixin):
    """Collect the standard records produced for one benchmark run.

    Attributes:
        run_id: Identifier of the benchmark run.
        task_kind: Registered name of the task adapter used by the run.
        config: Resolved declarative suite configuration.
        items: Task-defined benchmark items included in the result.
        runs: Lifecycle records for evaluated item and model pairs.
        predictions: Prediction records emitted by execution.
        metrics: Scalar metric records emitted by evaluation.
        artifact_manifest: Artifact references associated with the run.
        metadata: Read-only consumer-defined JSON metadata.
        schema_version: Version of the serialized schema.
    """

    run_id: str
    task_kind: str
    config: BenchmarkSuiteConfig
    items: tuple[ItemRecord, ...]
    runs: tuple[RunRecord, ...]
    predictions: tuple[PredictionRecord, ...]
    metrics: tuple[MetricRecord, ...]
    artifact_manifest: ArtifactManifest
    metadata: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ensure_schema_version(self.schema_version, schema_name="BenchmarkResult")
        _name(self.run_id, "BenchmarkResult.run_id")
        _name(self.task_kind, "BenchmarkResult.task_kind")
        if not isinstance(self.config, BenchmarkSuiteConfig):
            raise SchemaError("BenchmarkResult.config must be a BenchmarkSuiteConfig")
        if not isinstance(self.artifact_manifest, ArtifactManifest):
            raise SchemaError("BenchmarkResult.artifact_manifest must be an ArtifactManifest")
        items = tuple(self.items)
        runs = tuple(self.runs)
        predictions = tuple(self.predictions)
        metrics = tuple(self.metrics)
        _validate_items_and_record_ids(items, runs, predictions, metrics)
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "runs", runs)
        object.__setattr__(self, "predictions", predictions)
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(
            self,
            "metadata",
            _frozen_object(self.metadata, path="BenchmarkResult.metadata"),
        )
        if self.task_kind != self.config.task_kind:
            raise SchemaError("BenchmarkResult.task_kind must match its config")
        if self.artifact_manifest.run_id != self.run_id:
            raise SchemaError("ArtifactManifest.run_id must match BenchmarkResult.run_id")

        dataset_ids = {spec.dataset_id for spec in self.config.datasets}
        model_ids = {spec.model_id for spec in self.config.models}
        metric_ids = {spec.metric_id for spec in self.config.metrics}
        for item in items:
            if item.dataset_id not in dataset_ids:
                raise SchemaError(f"ItemRecord has an unknown dataset_id: {item.dataset_id!r}")
        for record in (*runs, *predictions, *metrics):
            if record.run_id != self.run_id:
                raise SchemaError(f"Record {record.record_id!r} has a foreign run_id")
            if record.dataset_id not in dataset_ids:
                raise SchemaError(f"Record {record.record_id!r} has an unknown dataset_id")
            if record.model_id not in model_ids:
                raise SchemaError(f"Record {record.record_id!r} has an unknown model_id")
        for record in metrics:
            if record.metric_id not in metric_ids:
                raise SchemaError(f"MetricRecord {record.record_id!r} has an unknown metric_id")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkResult":
        config = _mapping(data.get("config"), path="BenchmarkResult.config")
        manifest = _mapping(
            data.get("artifact_manifest"), path="BenchmarkResult.artifact_manifest"
        )
        items = array_value(data, "items", schema_name="BenchmarkResult", required=True)
        runs = array_value(data, "runs", schema_name="BenchmarkResult", required=True)
        predictions = array_value(data, "predictions", schema_name="BenchmarkResult", required=True)
        metrics = array_value(data, "metrics", schema_name="BenchmarkResult", required=True)
        return cls(
            run_id=require_string(data, "run_id", schema_name="BenchmarkResult"),
            task_kind=require_string(data, "task_kind", schema_name="BenchmarkResult"),
            config=BenchmarkSuiteConfig.from_dict(config),
            items=tuple(
                ItemRecord.from_dict(_mapping(item, path="BenchmarkResult.items[]"))
                for item in items
            ),
            runs=tuple(
                RunRecord.from_dict(_mapping(item, path="BenchmarkResult.runs[]"))
                for item in runs
            ),
            predictions=tuple(
                PredictionRecord.from_dict(
                    _mapping(item, path="BenchmarkResult.predictions[]")
                )
                for item in predictions
            ),
            metrics=tuple(
                MetricRecord.from_dict(_mapping(item, path="BenchmarkResult.metrics[]"))
                for item in metrics
            ),
            artifact_manifest=ArtifactManifest.from_dict(manifest),
            metadata=object_value(data, "metadata", schema_name="BenchmarkResult"),
            schema_version=require_schema_version(data, schema_name="BenchmarkResult"),
        )
