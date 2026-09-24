from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Protocol, cast, runtime_checkable

import pytest

from examples.custom_plugins import build_config, build_registries
from roast.core.config import (
    ArtifactSpec,
    BenchmarkSuiteConfig,
    DatasetSpec,
    MetricSpec,
    ModelSpec,
    PluginSpec,
    RunSpec,
)
from roast.core.events import Availability, ProgressEvent
from roast.core.records import ArtifactRecord, BenchmarkResult, ItemRecord
from roast.core.schema import JSONObject, ReadonlyJSONObject, to_plain_data
from roast.core.status import RunStatus
from roast.execution.artifacts import ErrorArtifactSink
from roast.execution.errors import (
    ExecutionError,
    ItemNotAvailable,
    SkipItem,
    SuiteExecutionError,
)
from roast.execution.orchestrator import PluginRegistries, SuiteOrchestrator, run_suite
from roast.execution.policy import ExecutionPolicy
from roast.plugins.errors import UnknownPluginError
from roast.plugins.registry import Registry, TaskKindRegistry
from roast.protocols.dataset import DatasetProvider
from roast.protocols.metric import Metric, MetricInput
from roast.protocols.model import ModelAdapter
from roast.protocols.task import ItemExecutionContext, PredictionOutput


class MemoryResumeStore:
    def __init__(self) -> None:
        self.states: dict[str, JSONObject] = {}
        self.save_count = 0

    def load(self, run_id: str) -> JSONObject | None:
        return self.states.get(run_id)

    def save(self, run_id: str, state: ReadonlyJSONObject) -> None:
        self.states[run_id] = cast(JSONObject, to_plain_data(state))
        self.save_count += 1


class ProgressCollector:
    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    def on_event(self, event: ProgressEvent) -> None:
        self.events.append(event)


class MemoryErrorSink(ErrorArtifactSink):
    def __init__(self) -> None:
        self.errors: tuple[ExecutionError, ...] = ()
        self.calls = 0

    def persist_errors(
        self,
        run_id: str,
        errors: tuple[ExecutionError, ...],
        spec: ArtifactSpec,
    ) -> ArtifactRecord:
        self.calls += 1
        self.errors = errors
        return ArtifactRecord(
            artifact_id="errors",
            kind="execution_errors",
            uri=f"{spec.output_uri}/errors.json",
            media_type="application/json",
        )


class ValuesProvider:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        self._values = tuple(options.get("values", ()))

    def load(self, spec: DatasetSpec) -> tuple[ItemRecord, ...]:
        return tuple(
            ItemRecord(
                item_id=f"item-{index}",
                dataset_id=spec.dataset_id,
                payload=value,
                target=value,
            )
            for index, value in enumerate(self._values)
        )


class OrderedValuesProvider(ValuesProvider):
    loaded_datasets: list[str] = []

    def load(self, spec: DatasetSpec) -> tuple[ItemRecord, ...]:
        type(self).loaded_datasets.append(spec.dataset_id)
        return super().load(spec)


class InvalidItemProvider:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def load(self, spec: DatasetSpec) -> tuple[object, ...]:
        return ("not-an-item",)


class WrongDatasetProvider:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def load(self, spec: DatasetSpec) -> tuple[ItemRecord, ...]:
        return (ItemRecord("wrong-dataset-item", "other-dataset", payload=1),)


class DuplicateItemProvider:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def load(self, spec: DatasetSpec) -> tuple[ItemRecord, ...]:
        item = ItemRecord("duplicate", spec.dataset_id, payload=1)
        return item, item


class MutableValuesProvider:
    values: tuple[int, ...] = (1, 2)

    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def load(self, spec: DatasetSpec) -> tuple[ItemRecord, ...]:
        return tuple(
            ItemRecord(f"item-{index}", spec.dataset_id, payload=value, target=value)
            for index, value in enumerate(type(self).values)
        )


class IdentityModel:
    calls = 0

    def __init__(self, options: ReadonlyJSONObject) -> None:
        self._available = bool(options.get("available", True))

    def availability(self) -> Availability:
        return Availability(
            available=self._available,
            reason="optional dependency is missing" if not self._available else "",
        )

    def predict(self, item: ItemRecord) -> object:
        type(self).calls += 1
        return item.payload


class AvailabilityFailureModel:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def availability(self) -> Availability:
        raise RuntimeError("availability failed")


class InvalidAvailabilityModel:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def availability(self) -> object:
        return object()


def failing_model_factory(options: ReadonlyJSONObject) -> ModelAdapter:
    raise RuntimeError("model factory failed")


class IdentityTask:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def execute_item(
        self,
        item: ItemRecord,
        model: ModelAdapter,
        context: ItemExecutionContext,
    ) -> PredictionOutput:
        return PredictionOutput(
            prediction=model.predict(item),  # type: ignore[attr-defined]
            truth=item.target,
            metadata={"semantics": "identity"},
        )


class ClassificationProvider:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def load(self, spec: DatasetSpec) -> tuple[ItemRecord, ...]:
        return (
            ItemRecord(
                item_id="classification-fold",
                dataset_id=spec.dataset_id,
                payload={
                    "train_features": [[0.0], [1.0], [2.0]],
                    "train_labels": ["low", "high", "high"],
                    "test_features": [1.5],
                },
                target="high",
            ),
        )


@runtime_checkable
class ClassifierCapability(ModelAdapter, Protocol):
    def predict_label(
        self,
        train_features: tuple[tuple[float, ...], ...],
        train_labels: tuple[str, ...],
        test_features: tuple[float, ...],
    ) -> str: ...


class MajorityClassifier:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def availability(self) -> Availability:
        return Availability(available=True)

    def predict_label(
        self,
        train_features: tuple[tuple[float, ...], ...],
        train_labels: tuple[str, ...],
        test_features: tuple[float, ...],
    ) -> str:
        if not train_features or not train_labels or not test_features:
            raise ValueError("classification data must not be empty")
        labels_in_order = tuple(dict.fromkeys(train_labels))
        return max(labels_in_order, key=train_labels.count)


class ClassificationTask:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def execute_item(
        self,
        item: ItemRecord,
        model: ModelAdapter,
        context: ItemExecutionContext,
    ) -> PredictionOutput:
        if not isinstance(model, ClassifierCapability):
            raise TypeError("classification requires ClassifierCapability")
        if not isinstance(item.payload, Mapping):
            raise TypeError("classification payload must be an object")
        train_features = tuple(
            tuple(float(value) for value in row)
            for row in item.payload["train_features"]
        )
        train_labels = tuple(str(value) for value in item.payload["train_labels"])
        test_features = tuple(
            float(value) for value in item.payload["test_features"]
        )
        return PredictionOutput(
            prediction=model.predict_label(
                train_features,
                train_labels,
                test_features,
            ),
            truth=item.target,
            metadata={"semantics": "classification", "output": "label"},
        )


class ForecastingProvider:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def load(self, spec: DatasetSpec) -> tuple[ItemRecord, ...]:
        return (
            ItemRecord(
                item_id="forecast-series",
                dataset_id=spec.dataset_id,
                payload={"history": [1.0, 2.0, 3.0], "horizon": 2},
                target=[4.0, 5.0],
            ),
        )


@runtime_checkable
class ForecasterCapability(ModelAdapter, Protocol):
    def forecast(
        self,
        history: tuple[float, ...],
        horizon: int,
    ) -> tuple[float, ...]: ...


class LinearTrendForecaster:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def availability(self) -> Availability:
        return Availability(available=True)

    def forecast(
        self,
        history: tuple[float, ...],
        horizon: int,
    ) -> tuple[float, ...]:
        if len(history) < 2:
            raise ValueError("forecasting requires at least two history values")
        step = history[-1] - history[-2]
        return tuple(history[-1] + step * offset for offset in range(1, horizon + 1))


class ForecastingTask:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def execute_item(
        self,
        item: ItemRecord,
        model: ModelAdapter,
        context: ItemExecutionContext,
    ) -> PredictionOutput:
        if not isinstance(model, ForecasterCapability):
            raise TypeError("forecasting requires ForecasterCapability")
        if not isinstance(item.payload, Mapping):
            raise TypeError("forecasting payload must be an object")
        history = tuple(float(value) for value in item.payload["history"])
        horizon = item.payload["horizon"]
        if type(horizon) is not int:
            raise TypeError("forecasting horizon must be an integer")
        return PredictionOutput(
            prediction=model.forecast(history, horizon),
            truth=item.target,
            metadata={
                "semantics": "forecasting",
                "output": "forecast_sequence",
                "horizon": horizon,
            },
        )


class FailingTask:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def execute_item(
        self,
        item: ItemRecord,
        model: ModelAdapter,
        context: ItemExecutionContext,
    ) -> PredictionOutput:
        raise RuntimeError(f"cannot execute {item.item_id}")


class SkipTask:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def execute_item(
        self,
        item: ItemRecord,
        model: ModelAdapter,
        context: ItemExecutionContext,
    ) -> PredictionOutput:
        raise SkipItem(f"skip {item.item_id}")


class NotAvailableTask:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def execute_item(
        self,
        item: ItemRecord,
        model: ModelAdapter,
        context: ItemExecutionContext,
    ) -> PredictionOutput:
        raise ItemNotAvailable(f"unavailable {item.item_id}")


class InvalidOutputTask:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def execute_item(
        self,
        item: ItemRecord,
        model: ModelAdapter,
        context: ItemExecutionContext,
    ) -> PredictionOutput:
        return cast(PredictionOutput, object())


class FlakyTask:
    fail = True
    calls = 0

    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def execute_item(
        self,
        item: ItemRecord,
        model: ModelAdapter,
        context: ItemExecutionContext,
    ) -> PredictionOutput:
        type(self).calls += 1
        if type(self).fail:
            raise RuntimeError(f"temporary failure for {item.item_id}")
        return PredictionOutput(prediction=item.payload, truth=item.target)


class ExactMatch:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def compute(self, value: MetricInput) -> float:
        return float(value.truth == value.prediction)


class FailingMetric:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def compute(self, value: MetricInput) -> float:
        raise RuntimeError("metric failed")


class FlakyMetric:
    fail = True
    calls = 0

    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def compute(self, value: MetricInput) -> float:
        type(self).calls += 1
        if type(self).fail:
            raise RuntimeError("temporary metric failure")
        return float(value.truth == value.prediction)


class InvalidErrorSink:
    def persist_errors(
        self,
        run_id: str,
        errors: tuple[ExecutionError, ...],
        spec: ArtifactSpec,
    ) -> ArtifactRecord:
        return cast(ArtifactRecord, object())


def make_registries() -> PluginRegistries:
    datasets: Registry[DatasetProvider] = Registry("dataset provider")
    models: Registry[ModelAdapter] = Registry("model adapter")
    metrics: Registry[Metric] = Registry("metric")
    tasks = TaskKindRegistry()
    datasets.register("toy.values", ValuesProvider)
    datasets.register("toy.ordered_values", OrderedValuesProvider)
    datasets.register("toy.invalid_item", InvalidItemProvider)
    datasets.register("toy.wrong_dataset", WrongDatasetProvider)
    datasets.register("toy.duplicate_item", DuplicateItemProvider)
    datasets.register("toy.mutable_values", MutableValuesProvider)
    datasets.register("toy.classification_data", ClassificationProvider)
    datasets.register("toy.forecasting_data", ForecastingProvider)
    models.register("toy.identity", IdentityModel)
    models.register("toy.majority_classifier", MajorityClassifier)
    models.register("toy.linear_trend", LinearTrendForecaster)
    models.register("toy.availability_failure", AvailabilityFailureModel)
    models.register("toy.invalid_availability", InvalidAvailabilityModel)
    models.register("toy.factory_failure", failing_model_factory)
    metrics.register("toy.exact", ExactMatch)
    metrics.register("toy.failing_metric", FailingMetric)
    metrics.register("toy.flaky_metric", FlakyMetric)
    tasks.register("toy.identity", IdentityTask)
    tasks.register("toy.classification", ClassificationTask)
    tasks.register("toy.forecasting", ForecastingTask)
    tasks.register("toy.failing", FailingTask)
    tasks.register("toy.skip", SkipTask)
    tasks.register("toy.not_available", NotAvailableTask)
    tasks.register("toy.invalid_output", InvalidOutputTask)
    tasks.register("toy.flaky", FlakyTask)
    return PluginRegistries(datasets, models, metrics, tasks)


def make_config(
    task_kind: str,
    *,
    datasets: tuple[DatasetSpec, ...] | None = None,
    models: tuple[ModelSpec, ...] | None = None,
    metrics: tuple[MetricSpec, ...] | None = None,
    run: RunSpec | None = None,
    persist: bool = False,
) -> BenchmarkSuiteConfig:
    return BenchmarkSuiteConfig(
        task_kind=task_kind,
        datasets=datasets
        or (
            DatasetSpec(
                dataset_id="toy-data",
                provider=PluginSpec("toy.values", {"values": [1, 2]}),
            ),
        ),
        models=models
        or (
            ModelSpec(
                model_id="identity",
                adapter=PluginSpec("toy.identity"),
            ),
        ),
        metrics=metrics or (MetricSpec("exact", PluginSpec("toy.exact")),),
        artifacts=ArtifactSpec("memory://results", persist=persist),
        run=run or RunSpec(run_name="toy", primary_metric="exact"),
    )


def make_distinct_task_config(task_kind: str) -> BenchmarkSuiteConfig:
    if task_kind == "toy.classification":
        provider_name = "toy.classification_data"
        model_id = "majority"
        adapter_name = "toy.majority_classifier"
    elif task_kind == "toy.forecasting":
        provider_name = "toy.forecasting_data"
        model_id = "linear-trend"
        adapter_name = "toy.linear_trend"
    else:
        raise ValueError(f"Unsupported test task kind: {task_kind}")

    return BenchmarkSuiteConfig(
        task_kind=task_kind,
        datasets=(
            DatasetSpec(
                dataset_id=f"{task_kind}-data",
                provider=PluginSpec(provider_name),
            ),
        ),
        models=(ModelSpec(model_id, PluginSpec(adapter_name)),),
        metrics=(MetricSpec("exact", PluginSpec("toy.exact")),),
        artifacts=ArtifactSpec("memory://results", persist=False),
        run=RunSpec(run_name=task_kind, primary_metric="exact"),
    )


def test_contract_example_runs_end_to_end() -> None:
    datasets, models, metrics, tasks = build_registries()

    result = run_suite(
        build_config(),
        PluginRegistries(datasets, models, metrics, tasks),
    )

    assert [record.status for record in result.runs] == [
        RunStatus.SUCCESS,
        RunStatus.SUCCESS,
        RunStatus.SUCCESS,
    ]
    assert [record.value for record in result.metrics] == [0.0, 0.0, 0.0]
    assert len(result.predictions) == 3
    assert BenchmarkResult.from_dict(result.to_dict()) == result


def test_one_orchestrator_runs_classification_and_forecasting_semantics() -> None:
    registries = make_registries()

    classification = run_suite(
        make_distinct_task_config("toy.classification"),
        registries,
    )
    forecasting = run_suite(
        make_distinct_task_config("toy.forecasting"),
        registries,
    )

    assert classification.runs[0].status is RunStatus.SUCCESS
    assert classification.predictions[0].prediction == "high"
    assert classification.predictions[0].metadata["output"] == "label"
    assert classification.metrics[0].value == 1.0

    assert forecasting.runs[0].status is RunStatus.SUCCESS
    assert forecasting.predictions[0].prediction == (4.0, 5.0)
    assert forecasting.predictions[0].metadata["output"] == "forecast_sequence"
    assert forecasting.predictions[0].metadata["horizon"] == 2
    assert forecasting.metrics[0].value == 1.0


def test_availability_maps_optional_to_skipped_and_required_to_not_available() -> None:
    models = (
        ModelSpec(
            "optional",
            PluginSpec("toy.identity", {"available": False}),
            optional=True,
        ),
        ModelSpec(
            "required",
            PluginSpec("toy.identity", {"available": False}),
        ),
    )

    result = run_suite(
        make_config("toy.identity", models=models),
        make_registries(),
    )

    assert [record.status for record in result.runs] == [
        RunStatus.SKIPPED,
        RunStatus.SKIPPED,
        RunStatus.NOT_AVAILABLE,
        RunStatus.NOT_AVAILABLE,
    ]
    assert result.predictions == ()
    assert result.metrics == ()


def test_failures_are_aggregated_and_optionally_persisted() -> None:
    sink = MemoryErrorSink()
    result = run_suite(
        make_config("toy.failing", persist=True),
        make_registries(),
        policy=ExecutionPolicy(
            include_traceback=True,
            persist_error_artifact=True,
        ),
        error_artifact_sink=sink,
    )

    assert [record.status for record in result.runs] == [
        RunStatus.FAILED,
        RunStatus.FAILED,
    ]
    assert len(result.metadata["errors"]) == 2
    assert len(sink.errors) == 2
    assert sink.errors[0].traceback is not None
    assert result.artifact_manifest.artifacts[0].artifact_id == "errors"

    serialized_error = sink.errors[0].to_dict()
    assert ExecutionError.from_dict(serialized_error) == sink.errors[0]


def test_resume_reuses_terminal_records_and_reports_progress() -> None:
    IdentityModel.calls = 0
    store = MemoryResumeStore()
    progress = ProgressCollector()
    first_config = make_config(
        "toy.identity",
        run=RunSpec(
            run_name="resumable",
            primary_metric="exact",
            resume_enabled=True,
        ),
    )
    first = run_suite(
        first_config,
        make_registries(),
        resume_store=store,
    )
    assert IdentityModel.calls == 2

    resumed_config = replace(
        first_config,
        run=replace(first_config.run, resume_run_id=first.run_id),
    )
    resumed = run_suite(
        resumed_config,
        make_registries(),
        resume_store=store,
        progress_hook=progress,
    )

    assert resumed.run_id == first.run_id
    assert IdentityModel.calls == 2
    assert len(resumed.runs) == 2
    assert [event.kind for event in progress.events].count("item_resumed") == 2
    assert progress.events[-1].kind == "suite_completed"
    assert store.save_count >= 4


def test_fail_fast_exposes_a_valid_partial_result() -> None:
    with pytest.raises(SuiteExecutionError) as caught:
        run_suite(
            make_config("toy.failing"),
            make_registries(),
            policy=ExecutionPolicy(fail_fast=True),
        )

    partial = caught.value.partial_result
    assert len(partial.runs) == 1
    assert partial.runs[0].status is RunStatus.FAILED


def test_provider_and_model_order_is_preserved() -> None:
    OrderedValuesProvider.loaded_datasets = []
    datasets = (
        DatasetSpec("first", PluginSpec("toy.ordered_values", {"values": [1, 2]})),
        DatasetSpec("second", PluginSpec("toy.ordered_values", {"values": [3]})),
    )
    models = (
        ModelSpec("model-a", PluginSpec("toy.identity")),
        ModelSpec("model-b", PluginSpec("toy.identity")),
    )

    result = run_suite(
        make_config("toy.identity", datasets=datasets, models=models),
        make_registries(),
    )

    assert OrderedValuesProvider.loaded_datasets == ["first", "second"]
    assert [(item.dataset_id, item.item_id) for item in result.items] == [
        ("first", "item-0"),
        ("first", "item-1"),
        ("second", "item-0"),
    ]
    assert [
        (record.model_id, record.dataset_id, record.item_id)
        for record in result.runs
    ] == [
        ("model-a", "first", "item-0"),
        ("model-a", "first", "item-1"),
        ("model-a", "second", "item-0"),
        ("model-b", "first", "item-0"),
        ("model-b", "first", "item-1"),
        ("model-b", "second", "item-0"),
    ]


@pytest.mark.parametrize(
    ("provider_name", "error_type", "message"),
    [
        ("toy.invalid_item", TypeError, "expected ItemRecord"),
        ("toy.wrong_dataset", ValueError, "with dataset_id 'other-dataset'"),
        ("toy.duplicate_item", ValueError, "duplicate item"),
    ],
)
def test_dataset_provider_output_is_validated(
    provider_name: str,
    error_type: type[Exception],
    message: str,
) -> None:
    config = make_config(
        "toy.identity",
        datasets=(DatasetSpec("toy-data", PluginSpec(provider_name)),),
    )

    with pytest.raises(error_type, match=message):
        run_suite(config, make_registries())


@pytest.mark.parametrize(
    ("task_kind", "expected_status", "message"),
    [
        ("toy.skip", RunStatus.SKIPPED, "skip item-0"),
        ("toy.not_available", RunStatus.NOT_AVAILABLE, "unavailable item-0"),
    ],
)
def test_task_control_flow_maps_to_terminal_status_without_errors(
    task_kind: str,
    expected_status: RunStatus,
    message: str,
) -> None:
    result = run_suite(make_config(task_kind), make_registries())

    assert [record.status for record in result.runs] == [expected_status] * 2
    assert result.runs[0].message == message
    assert result.predictions == ()
    assert result.metrics == ()
    assert result.metadata["errors"] == ()
    assert result.metadata["status_counts"] == {expected_status.value: 2}


def test_invalid_task_output_is_aggregated_as_a_task_failure() -> None:
    result = run_suite(make_config("toy.invalid_output"), make_registries())
    errors = tuple(
        ExecutionError.from_dict(cast(Mapping[str, object], value))
        for value in result.metadata["errors"]
    )

    assert [record.status for record in result.runs] == [RunStatus.FAILED] * 2
    assert result.predictions == ()
    assert result.metrics == ()
    assert [error.stage for error in errors] == ["task", "task"]
    assert all(error.exception_type == "builtins.TypeError" for error in errors)
    assert all(error.traceback is None for error in errors)


@pytest.mark.parametrize(
    ("adapter_name", "stage", "exception_type", "message"),
    [
        (
            "toy.factory_failure",
            "model_factory",
            "builtins.RuntimeError",
            "model factory failed",
        ),
        (
            "toy.availability_failure",
            "availability",
            "builtins.RuntimeError",
            "availability failed",
        ),
        (
            "toy.invalid_availability",
            "availability",
            "builtins.TypeError",
            "must return Availability",
        ),
    ],
)
def test_model_resolution_and_availability_errors_are_aggregated(
    adapter_name: str,
    stage: str,
    exception_type: str,
    message: str,
) -> None:
    progress = ProgressCollector()
    models = (ModelSpec("broken", PluginSpec(adapter_name)),)

    result = run_suite(
        make_config("toy.identity", models=models),
        make_registries(),
        progress_hook=progress,
    )
    errors = tuple(
        ExecutionError.from_dict(cast(Mapping[str, object], value))
        for value in result.metadata["errors"]
    )

    assert [record.status for record in result.runs] == [RunStatus.FAILED] * 2
    assert [error.stage for error in errors] == [stage, stage]
    assert all(error.exception_type == exception_type for error in errors)
    assert all(message in error.message for error in errors)
    assert result.metadata["status_counts"] == {"failed": 2}
    assert progress.events[-1].kind == "suite_failed"


def test_unknown_model_name_is_a_configuration_error() -> None:
    models = (ModelSpec("broken", PluginSpec("toy.missing_model")),)
    with pytest.raises(UnknownPluginError, match="registered model adapter names"):
        run_suite(make_config("toy.identity", models=models), make_registries())


def test_metric_failure_keeps_prediction_and_other_metric_results() -> None:
    metrics = (
        MetricSpec("broken", PluginSpec("toy.failing_metric")),
        MetricSpec("exact", PluginSpec("toy.exact")),
    )

    result = run_suite(
        make_config("toy.identity", metrics=metrics),
        make_registries(),
    )

    assert [record.status for record in result.runs] == [RunStatus.FAILED] * 2
    assert len(result.predictions) == 2
    assert [record.metric_id for record in result.metrics] == [
        "broken",
        "exact",
        "broken",
        "exact",
    ]
    assert [record.status for record in result.metrics] == [
        RunStatus.FAILED,
        RunStatus.SUCCESS,
        RunStatus.FAILED,
        RunStatus.SUCCESS,
    ]
    assert [record.value for record in result.metrics] == [None, 1.0, None, 1.0]
    assert all(
        "error_id" in record.metadata
        for record in result.metrics
        if record.status is RunStatus.FAILED
    )
    assert len(result.metadata["errors"]) == 2


def test_resume_replaces_failed_metric_outputs_instead_of_duplicating_them() -> None:
    FlakyMetric.fail = True
    FlakyMetric.calls = 0
    store = MemoryResumeStore()
    metrics = (MetricSpec("flaky", PluginSpec("toy.flaky_metric")),)
    config = make_config(
        "toy.identity",
        metrics=metrics,
        run=RunSpec(
            run_name="retry-metric",
            primary_metric="flaky",
            resume_enabled=True,
        ),
    )
    first = run_suite(config, make_registries(), resume_store=store)
    assert [record.status for record in first.runs] == [RunStatus.FAILED] * 2
    assert len(first.predictions) == 2
    assert len(first.metrics) == 2

    FlakyMetric.fail = False
    resumed = run_suite(
        replace(config, run=replace(config.run, resume_run_id=first.run_id)),
        make_registries(),
        resume_store=store,
    )

    assert FlakyMetric.calls == 4
    assert [record.status for record in resumed.runs] == [RunStatus.SUCCESS] * 2
    assert len(resumed.predictions) == 2
    assert len(resumed.metrics) == 2
    assert [record.value for record in resumed.metrics] == [1.0, 1.0]
    assert resumed.metadata["errors"] == ()


def test_successful_resume_removes_stale_error_artifact() -> None:
    FlakyTask.fail = True
    store = MemoryResumeStore()
    sink = MemoryErrorSink()
    config = make_config(
        "toy.flaky",
        persist=True,
        run=RunSpec(run_name="error-artifact-retry", resume_enabled=True),
    )
    policy = ExecutionPolicy(persist_error_artifact=True)
    first = run_suite(
        config, make_registries(), policy=policy,
        resume_store=store, error_artifact_sink=sink,
    )
    assert first.artifact_manifest.artifacts[0].kind == "execution_errors"

    FlakyTask.fail = False
    resumed = run_suite(
        replace(config, run=replace(config.run, resume_run_id=first.run_id)),
        make_registries(), policy=policy,
        resume_store=store, error_artifact_sink=sink,
    )
    assert resumed.metadata["errors"] == ()
    assert resumed.artifact_manifest.artifacts == ()
    assert store.states[first.run_id]["artifact_manifest"]["artifacts"] == []
    assert sink.calls == 1


@pytest.mark.parametrize(
    ("stage", "dataset_id", "metric_id"),
    [
        ("dataset_factory", "toy-data", None),
        ("dataset_load", "toy-data", None),
        ("task_factory", None, None),
        ("metric_factory", None, "exact"),
    ],
)
def test_plugin_setup_failures_have_partial_result_and_error_artifact(
    stage: str, dataset_id: str | None, metric_id: str | None
) -> None:
    registries = make_registries()
    config = make_config("toy.identity", persist=True)

    def failing_factory(options: ReadonlyJSONObject) -> object:
        raise RuntimeError(f"{stage} failed")

    class FailingProvider:
        def __init__(self, options: ReadonlyJSONObject) -> None:
            pass

        def load(self, spec: DatasetSpec):
            yield ItemRecord("first", spec.dataset_id, payload=1)
            raise RuntimeError("dataset_load failed")

    if stage == "dataset_factory":
        registries.datasets.register("toy.setup_failure", failing_factory)
        config = replace(config, datasets=(
            DatasetSpec("toy-data", PluginSpec("toy.setup_failure")),
        ))
    elif stage == "dataset_load":
        registries.datasets.register("toy.setup_failure", FailingProvider)
        config = replace(config, datasets=(
            DatasetSpec("toy-data", PluginSpec("toy.setup_failure")),
        ))
    elif stage == "task_factory":
        registries.tasks.register("toy.setup_failure", failing_factory)
        config = replace(config, task_kind="toy.setup_failure")
    else:
        registries.metrics.register("toy.setup_failure", failing_factory)
        config = replace(config, metrics=(
            MetricSpec("exact", PluginSpec("toy.setup_failure")),
        ))

    progress = ProgressCollector()
    sink = MemoryErrorSink()
    store = MemoryResumeStore()
    config = replace(config, run=replace(config.run, resume_enabled=True))
    with pytest.raises(SuiteExecutionError) as caught:
        run_suite(
            config, registries,
            policy=ExecutionPolicy(persist_error_artifact=True),
            progress_hook=progress,
            resume_store=store,
            error_artifact_sink=sink,
        )
    partial = caught.value.partial_result
    error = ExecutionError.from_dict(partial.metadata["errors"][0])
    assert error.stage == stage
    assert error.dataset_id == dataset_id
    assert error.metric_id == metric_id
    assert partial.runs == ()
    assert len(partial.items) == (1 if stage == "dataset_load" else 0 if stage == "dataset_factory" else 2)
    assert [event.kind for event in progress.events] == ["suite_started", "suite_failed"]
    assert partial.artifact_manifest.artifacts[0].kind == "execution_errors"
    assert store.states == {}


def test_progress_reports_the_complete_success_lifecycle() -> None:
    progress = ProgressCollector()

    run_suite(
        make_config("toy.identity"),
        make_registries(),
        progress_hook=progress,
    )

    assert [event.kind for event in progress.events] == [
        "suite_started",
        "item_started",
        "item_completed",
        "item_started",
        "item_completed",
        "suite_completed",
    ]
    assert [event.current for event in progress.events] == [0, 0, 1, 1, 2, 2]
    assert all(event.total == 2 for event in progress.events)
    assert progress.events[2].metadata == {
        "dataset_id": "toy-data",
        "model_id": "identity",
        "item_id": "item-0",
        "status": "success",
    }


def test_error_artifact_requires_a_sink_only_when_persistence_is_enabled() -> None:
    policy = ExecutionPolicy(persist_error_artifact=True)

    with pytest.raises(ValueError, match="requires an ErrorArtifactSink"):
        run_suite(
            make_config("toy.failing", persist=True),
            make_registries(),
            policy=policy,
        )

    result = run_suite(
        make_config("toy.failing", persist=False),
        make_registries(),
        policy=policy,
    )
    assert result.artifact_manifest.artifacts == ()


def test_error_sink_is_not_called_without_errors() -> None:
    sink = MemoryErrorSink()

    result = run_suite(
        make_config("toy.identity", persist=True),
        make_registries(),
        policy=ExecutionPolicy(persist_error_artifact=True),
        error_artifact_sink=sink,
    )

    assert sink.calls == 0
    assert result.artifact_manifest.artifacts == ()


def test_error_sink_must_return_an_artifact_record() -> None:
    with pytest.raises(TypeError, match="must return ArtifactRecord"):
        run_suite(
            make_config("toy.failing", persist=True),
            make_registries(),
            policy=ExecutionPolicy(persist_error_artifact=True),
            error_artifact_sink=InvalidErrorSink(),
        )


def test_error_sink_must_label_its_artifact() -> None:
    class WrongKindSink:
        def persist_errors(
            self, run_id: str, errors: tuple[ExecutionError, ...], spec: ArtifactSpec
        ) -> ArtifactRecord:
            return ArtifactRecord(
                artifact_id="wrong", kind="other", uri="memory://wrong",
                media_type="application/json",
            )

    with pytest.raises(ValueError, match="kind='execution_errors'"):
        run_suite(
            make_config("toy.failing", persist=True),
            make_registries(),
            policy=ExecutionPolicy(persist_error_artifact=True),
            error_artifact_sink=WrongKindSink(),
        )


def test_resume_requires_a_store() -> None:
    config = make_config(
        "toy.identity",
        run=RunSpec(run_name="missing-store", resume_enabled=True),
    )

    with pytest.raises(ValueError, match="requires a ResumeStore"):
        run_suite(config, make_registries())


def test_resume_retries_failed_pairs_by_default() -> None:
    FlakyTask.fail = True
    FlakyTask.calls = 0
    store = MemoryResumeStore()
    config = make_config(
        "toy.flaky",
        run=RunSpec(run_name="retry-failed", resume_enabled=True),
    )
    first = run_suite(config, make_registries(), resume_store=store)
    assert [record.status for record in first.runs] == [RunStatus.FAILED] * 2

    FlakyTask.fail = False
    resumed = run_suite(
        replace(config, run=replace(config.run, resume_run_id=first.run_id)),
        make_registries(),
        resume_store=store,
    )

    assert FlakyTask.calls == 4
    assert [record.status for record in resumed.runs] == [RunStatus.SUCCESS] * 2
    assert resumed.metadata["errors"] == ()


def test_resume_can_retain_failed_pairs_without_retrying() -> None:
    FlakyTask.fail = True
    FlakyTask.calls = 0
    store = MemoryResumeStore()
    config = make_config(
        "toy.flaky",
        run=RunSpec(run_name="retain-failed", resume_enabled=True),
    )
    first = run_suite(config, make_registries(), resume_store=store)

    FlakyTask.fail = False
    resumed = run_suite(
        replace(config, run=replace(config.run, resume_run_id=first.run_id)),
        make_registries(),
        policy=ExecutionPolicy(retry_failed_on_resume=False),
        resume_store=store,
    )

    assert FlakyTask.calls == 2
    assert [record.status for record in resumed.runs] == [RunStatus.FAILED] * 2
    assert len(resumed.metadata["errors"]) == 2


def test_resume_rejects_an_incompatible_config() -> None:
    store = MemoryResumeStore()
    config = make_config(
        "toy.identity",
        run=RunSpec(run_name="incompatible", resume_enabled=True),
    )
    first = run_suite(config, make_registries(), resume_store=store)
    resumed_config = replace(
        config,
        task_options={"changed": True},
        run=replace(config.run, resume_run_id=first.run_id),
    )

    with pytest.raises(ValueError, match="incompatible with the suite config"):
        run_suite(resumed_config, make_registries(), resume_store=store)


def test_resume_rejects_changed_provider_items() -> None:
    MutableValuesProvider.values = (1, 2)
    store = MemoryResumeStore()
    datasets = (DatasetSpec("toy-data", PluginSpec("toy.mutable_values")),)
    config = make_config(
        "toy.identity",
        datasets=datasets,
        run=RunSpec(run_name="changed-items", resume_enabled=True),
    )
    first = run_suite(config, make_registries(), resume_store=store)
    resumed_config = replace(
        config,
        run=replace(config.run, resume_run_id=first.run_id),
    )
    MutableValuesProvider.values = (1, 2, 3)

    with pytest.raises(ValueError, match="items differ from provider output"):
        run_suite(resumed_config, make_registries(), resume_store=store)

    MutableValuesProvider.values = (1, 2)


def test_resume_rejects_duplicate_item_model_records() -> None:
    store = MemoryResumeStore()
    config = make_config(
        "toy.identity",
        run=RunSpec(run_name="duplicate-runs", resume_enabled=True),
    )
    first = run_suite(config, make_registries(), resume_store=store)
    state = store.states[first.run_id]
    duplicate = dict(cast(list[JSONObject], state["runs"])[0])
    duplicate["record_id"] = "different-record-id"
    cast(list[JSONObject], state["runs"]).append(cast(JSONObject, duplicate))

    with pytest.raises(ValueError, match="duplicate item/model run records"):
        run_suite(
            replace(config, run=replace(config.run, resume_run_id=first.run_id)),
            make_registries(),
            resume_store=store,
        )


def test_resume_rejects_output_without_a_run_record() -> None:
    store = MemoryResumeStore()
    config = make_config(
        "toy.identity",
        run=RunSpec(run_name="orphan-output", resume_enabled=True),
    )
    first = run_suite(config, make_registries(), resume_store=store)
    state = store.states[first.run_id]
    state["runs"] = []

    with pytest.raises(ValueError, match="output without a run record"):
        run_suite(
            replace(config, run=replace(config.run, resume_run_id=first.run_id)),
            make_registries(),
            resume_store=store,
        )


@pytest.mark.parametrize("invalid_errors", ["not-an-array", ["not-an-object"]])
def test_resume_rejects_invalid_serialized_errors(
    invalid_errors: str | list[str],
) -> None:
    store = MemoryResumeStore()
    config = make_config(
        "toy.identity",
        run=RunSpec(run_name="invalid-errors", resume_enabled=True),
    )
    first = run_suite(config, make_registries(), resume_store=store)
    state = store.states[first.run_id]
    cast(JSONObject, state["metadata"])["errors"] = invalid_errors

    with pytest.raises(ValueError, match="metadata.errors"):
        run_suite(
            replace(config, run=replace(config.run, resume_run_id=first.run_id)),
            make_registries(),
            resume_store=store,
        )


def test_unknown_dataset_task_and_metric_plugins_are_reported() -> None:
    unknown_dataset = make_config(
        "toy.identity",
        datasets=(DatasetSpec("toy-data", PluginSpec("toy.missing_dataset")),),
    )
    with pytest.raises(UnknownPluginError, match="registered dataset provider names"):
        run_suite(unknown_dataset, make_registries())

    with pytest.raises(UnknownPluginError, match="registered task kind names"):
        run_suite(make_config("toy.missing_task"), make_registries())

    unknown_metric = make_config(
        "toy.identity",
        metrics=(MetricSpec("missing", PluginSpec("toy.missing_metric")),),
        run=RunSpec(primary_metric="missing"),
    )
    with pytest.raises(UnknownPluginError, match="registered metric names"):
        run_suite(unknown_metric, make_registries())


def test_orchestrator_rejects_invalid_public_arguments() -> None:
    registries = make_registries()

    with pytest.raises(TypeError, match="registries must be PluginRegistries"):
        SuiteOrchestrator(cast(PluginRegistries, object()))
    with pytest.raises(TypeError, match="policy must be an ExecutionPolicy"):
        SuiteOrchestrator(registries, policy=cast(ExecutionPolicy, object()))
    with pytest.raises(TypeError, match="clock must be callable"):
        SuiteOrchestrator(registries, clock=cast(object, None))
    with pytest.raises(TypeError, match="config must be a BenchmarkSuiteConfig"):
        SuiteOrchestrator(registries).run(cast(BenchmarkSuiteConfig, object()))


@pytest.mark.parametrize(
    "field_name",
    [
        "fail_fast",
        "include_traceback",
        "persist_error_artifact",
        "retry_failed_on_resume",
    ],
)
def test_execution_policy_rejects_non_boolean_values(field_name: str) -> None:
    with pytest.raises(TypeError, match=f"ExecutionPolicy.{field_name}"):
        ExecutionPolicy(**{field_name: 1})  # type: ignore[arg-type]
