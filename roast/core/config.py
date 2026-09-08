from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from roast.core.schema import (
    ReadonlyJSONObject,
    SCHEMA_VERSION,
    SchemaError,
    SchemaMixin,
    array_value,
    boolean_value,
    ensure_schema_version,
    integer_value,
    object_value,
    optional_string,
    require_schema_version,
    require_string,
    _frozen_object,
    _mapping,
    _name,
    _string_default,
)


@dataclass(frozen=True)
class PluginSpec(SchemaMixin):
    """Describe a plugin selected by a registered name.

    Attributes:
        name: Stable name used to resolve the plugin factory.
        options: Read-only JSON options passed to the factory.
        schema_version: Version of the serialized schema.
    """

    name: str
    options: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _name(self.name, "PluginSpec.name")
        ensure_schema_version(self.schema_version, schema_name="PluginSpec")
        object.__setattr__(
            self,
            "options",
            _frozen_object(self.options, path="PluginSpec.options"),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PluginSpec":
        return cls(
            name=require_string(data, "name", schema_name="PluginSpec"),
            options=object_value(data, "options", schema_name="PluginSpec"),
            schema_version=require_schema_version(data, schema_name="PluginSpec"),
        )


@dataclass(frozen=True)
class DatasetSpec(SchemaMixin):
    """Describe one configured dataset.

    Attributes:
        dataset_id: Identifier used by items and result records.
        provider: Registered dataset provider and its options.
        metadata: Read-only consumer-defined JSON metadata.
        schema_version: Version of the serialized schema.
    """

    dataset_id: str
    provider: PluginSpec
    metadata: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _name(self.dataset_id, "DatasetSpec.dataset_id")
        ensure_schema_version(self.schema_version, schema_name="DatasetSpec")
        if not isinstance(self.provider, PluginSpec):
            raise SchemaError("DatasetSpec.provider must be a PluginSpec")
        object.__setattr__(
            self,
            "metadata",
            _frozen_object(self.metadata, path="DatasetSpec.metadata"),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DatasetSpec":
        provider = _mapping(data.get("provider"), path="DatasetSpec.provider")
        return cls(
            dataset_id=require_string(data, "dataset_id", schema_name="DatasetSpec"),
            provider=PluginSpec.from_dict(provider),
            metadata=object_value(data, "metadata", schema_name="DatasetSpec"),
            schema_version=require_schema_version(data, schema_name="DatasetSpec"),
        )


@dataclass(frozen=True)
class ModelSpec(SchemaMixin):
    """Describe one configured model adapter.

    Attributes:
        model_id: Identifier used by run, prediction, and metric records.
        adapter: Registered model adapter and its options.
        tags: Labels available to filtering and reporting layers.
        optional: Whether an unavailable model may be skipped.
        metadata: Read-only consumer-defined JSON metadata.
        schema_version: Version of the serialized schema.
    """

    model_id: str
    adapter: PluginSpec
    tags: tuple[str, ...] = ()
    optional: bool = False
    metadata: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _name(self.model_id, "ModelSpec.model_id")
        ensure_schema_version(self.schema_version, schema_name="ModelSpec")
        if not isinstance(self.adapter, PluginSpec):
            raise SchemaError("ModelSpec.adapter must be a PluginSpec")
        tags = tuple(self.tags)
        if any(not isinstance(tag, str) for tag in tags):
            raise SchemaError("ModelSpec.tags must contain only strings")
        if type(self.optional) is not bool:
            raise SchemaError("ModelSpec.optional must be a boolean")
        object.__setattr__(self, "tags", tags)
        object.__setattr__(
            self,
            "metadata",
            _frozen_object(self.metadata, path="ModelSpec.metadata"),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelSpec":
        adapter = _mapping(data.get("adapter"), path="ModelSpec.adapter")
        tags = array_value(data, "tags", schema_name="ModelSpec")
        if any(not isinstance(tag, str) for tag in tags):
            raise SchemaError("ModelSpec.tags must contain only strings")
        return cls(
            model_id=require_string(data, "model_id", schema_name="ModelSpec"),
            adapter=PluginSpec.from_dict(adapter),
            tags=tuple(tags),
            optional=boolean_value(data, "optional", schema_name="ModelSpec", default=False),
            metadata=object_value(data, "metadata", schema_name="ModelSpec"),
            schema_version=require_schema_version(data, schema_name="ModelSpec"),
        )


@dataclass(frozen=True)
class MetricSpec(SchemaMixin):
    """Describe one configured metric.

    Attributes:
        metric_id: Identifier used by metric records.
        metric: Registered metric implementation and its options.
        schema_version: Version of the serialized schema.
    """

    metric_id: str
    metric: PluginSpec
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _name(self.metric_id, "MetricSpec.metric_id")
        ensure_schema_version(self.schema_version, schema_name="MetricSpec")
        if not isinstance(self.metric, PluginSpec):
            raise SchemaError("MetricSpec.metric must be a PluginSpec")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MetricSpec":
        metric = _mapping(data.get("metric"), path="MetricSpec.metric")
        return cls(
            metric_id=require_string(data, "metric_id", schema_name="MetricSpec"),
            metric=PluginSpec.from_dict(metric),
            schema_version=require_schema_version(data, schema_name="MetricSpec"),
        )


@dataclass(frozen=True)
class RunSpec(SchemaMixin):
    """Describe task-neutral options for a benchmark run.

    Attributes:
        run_name: Human-readable run name and identifier prefix.
        random_seed: Seed made available to execution layers.
        primary_metric: Metric identifier selected for primary reporting.
        resume_enabled: Whether a future execution layer may resume work.
        resume_run_id: Existing run identifier to resume, when specified.
        options: Read-only JSON options owned by execution policies.
        schema_version: Version of the serialized schema.
    """

    run_name: str = "benchmark"
    random_seed: int = 0
    primary_metric: str | None = None
    resume_enabled: bool = False
    resume_run_id: str | None = None
    options: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _name(self.run_name, "RunSpec.run_name")
        ensure_schema_version(self.schema_version, schema_name="RunSpec")
        if type(self.random_seed) is not int:
            raise SchemaError("RunSpec.random_seed must be an integer")
        if self.primary_metric is not None:
            _name(self.primary_metric, "RunSpec.primary_metric")
        if type(self.resume_enabled) is not bool:
            raise SchemaError("RunSpec.resume_enabled must be a boolean")
        if self.resume_run_id is not None:
            _name(self.resume_run_id, "RunSpec.resume_run_id")
        object.__setattr__(
            self,
            "options",
            _frozen_object(self.options, path="RunSpec.options"),
        )
        if self.resume_run_id and not self.resume_enabled:
            raise SchemaError("resume_run_id requires resume_enabled=True")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunSpec":
        return cls(
            run_name=_string_default(data, "run_name", schema_name="RunSpec", default="benchmark"),
            random_seed=integer_value(data, "random_seed", schema_name="RunSpec", default=0),
            primary_metric=optional_string(data, "primary_metric", schema_name="RunSpec"),
            resume_enabled=boolean_value(
                data, "resume_enabled", schema_name="RunSpec", default=False
            ),
            resume_run_id=optional_string(data, "resume_run_id", schema_name="RunSpec"),
            options=object_value(data, "options", schema_name="RunSpec"),
            schema_version=require_schema_version(data, schema_name="RunSpec"),
        )


@dataclass(frozen=True)
class ArtifactSpec(SchemaMixin):
    """Describe a task-neutral artifact destination policy.

    Attributes:
        output_uri: Root URI selected for future artifact persistence.
        persist: Whether an execution layer should persist artifacts.
        options: Read-only JSON options owned by artifact implementations.
        schema_version: Version of the serialized schema.
    """

    output_uri: str
    persist: bool = True
    options: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _name(self.output_uri, "ArtifactSpec.output_uri")
        ensure_schema_version(self.schema_version, schema_name="ArtifactSpec")
        if type(self.persist) is not bool:
            raise SchemaError("ArtifactSpec.persist must be a boolean")
        object.__setattr__(
            self,
            "options",
            _frozen_object(self.options, path="ArtifactSpec.options"),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactSpec":
        return cls(
            output_uri=require_string(data, "output_uri", schema_name="ArtifactSpec"),
            persist=boolean_value(data, "persist", schema_name="ArtifactSpec", default=True),
            options=object_value(data, "options", schema_name="ArtifactSpec"),
            schema_version=require_schema_version(data, schema_name="ArtifactSpec"),
        )


@dataclass(frozen=True)
class BenchmarkSuiteConfig(SchemaMixin):
    """Describe a complete benchmark suite through registered plugin names.

    Attributes:
        task_kind: Registered name of the selected task adapter.
        datasets: Dataset specifications included in the suite.
        models: Model specifications included in the suite.
        metrics: Metric specifications included in the suite.
        artifacts: Declarative artifact destination policy.
        run: Task-neutral run options.
        task_options: Read-only JSON options owned by the task adapter.
        schema_version: Version of the serialized schema.
    """

    task_kind: str
    datasets: tuple[DatasetSpec, ...]
    models: tuple[ModelSpec, ...]
    metrics: tuple[MetricSpec, ...]
    artifacts: ArtifactSpec
    run: RunSpec = field(default_factory=RunSpec)
    task_options: ReadonlyJSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _name(self.task_kind, "BenchmarkSuiteConfig.task_kind")
        ensure_schema_version(self.schema_version, schema_name="BenchmarkSuiteConfig")
        datasets = tuple(self.datasets)
        models = tuple(self.models)
        metrics = tuple(self.metrics)
        if any(not isinstance(spec, DatasetSpec) for spec in datasets):
            raise SchemaError("BenchmarkSuiteConfig.datasets must contain DatasetSpec values")
        if any(not isinstance(spec, ModelSpec) for spec in models):
            raise SchemaError("BenchmarkSuiteConfig.models must contain ModelSpec values")
        if any(not isinstance(spec, MetricSpec) for spec in metrics):
            raise SchemaError("BenchmarkSuiteConfig.metrics must contain MetricSpec values")
        for field_name, specs in (
            ("datasets", datasets),
            ("models", models),
            ("metrics", metrics),
        ):
            if not specs:
                raise SchemaError(
                    f"BenchmarkSuiteConfig.{field_name} must not be empty"
                )
        if not isinstance(self.artifacts, ArtifactSpec):
            raise SchemaError("BenchmarkSuiteConfig.artifacts must be an ArtifactSpec")
        if not isinstance(self.run, RunSpec):
            raise SchemaError("BenchmarkSuiteConfig.run must be a RunSpec")
        object.__setattr__(self, "datasets", datasets)
        object.__setattr__(self, "models", models)
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(
            self,
            "task_options",
            _frozen_object(self.task_options, path="BenchmarkSuiteConfig.task_options"),
        )
        configured_specs = (
            ("dataset", self.datasets),
            ("model", self.models),
            ("metric", self.metrics),
        )
        for label, specs in configured_specs:
            identifiers = [getattr(spec, f"{label}_id") for spec in specs]
            if len(identifiers) != len(set(identifiers)):
                raise SchemaError(f"Duplicate {label} ids are not allowed")
        if self.run.primary_metric and self.run.primary_metric not in {
            spec.metric_id for spec in self.metrics
        }:
            raise SchemaError("RunSpec.primary_metric must reference a configured metric_id")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkSuiteConfig":
        datasets = array_value(data, "datasets", schema_name="BenchmarkSuiteConfig", required=True)
        models = array_value(data, "models", schema_name="BenchmarkSuiteConfig", required=True)
        metrics = array_value(data, "metrics", schema_name="BenchmarkSuiteConfig", required=True)
        artifacts = _mapping(data.get("artifacts"), path="BenchmarkSuiteConfig.artifacts")
        run_value = data.get("run")
        run = RunSpec() if run_value is None else RunSpec.from_dict(
            _mapping(run_value, path="BenchmarkSuiteConfig.run")
        )
        return cls(
            task_kind=require_string(data, "task_kind", schema_name="BenchmarkSuiteConfig"),
            datasets=tuple(
                DatasetSpec.from_dict(_mapping(item, path="BenchmarkSuiteConfig.datasets[]"))
                for item in datasets
            ),
            models=tuple(
                ModelSpec.from_dict(_mapping(item, path="BenchmarkSuiteConfig.models[]"))
                for item in models
            ),
            metrics=tuple(
                MetricSpec.from_dict(_mapping(item, path="BenchmarkSuiteConfig.metrics[]"))
                for item in metrics
            ),
            artifacts=ArtifactSpec.from_dict(artifacts),
            run=run,
            task_options=object_value(data, "task_options", schema_name="BenchmarkSuiteConfig"),
            schema_version=require_schema_version(data, schema_name="BenchmarkSuiteConfig"),
        )
