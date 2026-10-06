from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from roast.core.config import (
    ArtifactSpec,
    BenchmarkSuiteConfig,
    DatasetSpec,
    MetricSpec,
    ModelSpec,
    PluginSpec,
    RunSpec,
)
from roast.core.events import Availability
from roast.core.records import ItemRecord
from roast.core.schema import ReadonlyJSONObject
from roast.execution.orchestrator import PluginRegistries
from roast.plugins.metrics import standard_metric_registry
from roast.plugins.registry import (
    DatasetProviderRegistry,
    MetricRegistry,
    ModelAdapterRegistry,
    PresetRegistry,
    TaskKindRegistry,
)
from roast.protocols.model import ModelAdapter
from roast.protocols.task import ItemExecutionContext, PredictionOutput


class ToyClassificationDataset:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        self.options = options

    def load(self, spec: DatasetSpec):
        yield ItemRecord(
            "case-a", spec.dataset_id,
            payload={"train_labels": ["red", "red", "blue"]}, target="red",
        )
        yield ItemRecord(
            "case-b", spec.dataset_id,
            payload={"train_labels": ["blue", "blue", "red"]}, target="blue",
        )


class ToyForecastDataset:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        self.options = options

    def load(self, spec: DatasetSpec):
        yield ItemRecord(
            "series-a", spec.dataset_id,
            payload={"history": [1, 2, 3], "horizon": 2}, target=[3, 3],
        )
        yield ItemRecord(
            "series-b", spec.dataset_id,
            payload={"history": [5, 4], "horizon": 2}, target=[4, 4],
        )


class MajorityClassifier:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def availability(self) -> Availability:
        return Availability(True)

    def predict_label(self, labels: tuple[object, ...]) -> object:
        if not labels:
            raise ValueError("train_labels must not be empty")
        return Counter(labels).most_common(1)[0][0]


class LastValueForecaster:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def availability(self) -> Availability:
        return Availability(True)

    def forecast(self, history: tuple[object, ...], horizon: int) -> list[object]:
        if not history:
            raise ValueError("history must not be empty")
        if horizon < 1:
            raise ValueError("horizon must be positive")
        return [history[-1]] * horizon


def _payload(item: ItemRecord) -> Mapping[str, object]:
    if not isinstance(item.payload, Mapping):
        raise TypeError("Toy item payload must be an object")
    return item.payload


class ClassificationTask:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def execute_item(
        self, item: ItemRecord, model: ModelAdapter, context: ItemExecutionContext
    ) -> PredictionOutput:
        if not hasattr(model, "predict_label"):
            raise TypeError("Classification model must define predict_label()")
        labels = _payload(item).get("train_labels")
        if not isinstance(labels, tuple):
            raise TypeError("train_labels must be an array")
        prediction = model.predict_label(labels)  # type: ignore[attr-defined]
        return PredictionOutput(prediction=prediction, truth=item.target)


class ForecastingTask:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def execute_item(
        self, item: ItemRecord, model: ModelAdapter, context: ItemExecutionContext
    ) -> PredictionOutput:
        if not hasattr(model, "forecast"):
            raise TypeError("Forecasting model must define forecast()")
        payload = _payload(item)
        history, horizon = payload.get("history"), payload.get("horizon")
        if not isinstance(history, tuple) or type(horizon) is not int:
            raise TypeError("history must be an array and horizon an integer")
        prediction = model.forecast(history, horizon)  # type: ignore[attr-defined]
        return PredictionOutput(prediction=prediction, truth=item.target)


def register_plugins(registries: PluginRegistries) -> None:
    registries.datasets.register("toy.classification", ToyClassificationDataset)
    registries.datasets.register("toy.forecasting", ToyForecastDataset)
    registries.models.register("toy.majority", MajorityClassifier)
    registries.models.register("toy.last_value", LastValueForecaster)
    registries.tasks.register("classification", ClassificationTask)
    registries.tasks.register("forecasting", ForecastingTask)
    standards = standard_metric_registry()
    for name in standards.names():
        metadata = standards.metadata(name)
        registries.metrics.register(
            name,
            standards.get(name),
            direction=metadata.direction,
            task_kinds=metadata.task_kinds,
            aliases=metadata.aliases,
        )


def build_registries() -> tuple[
    DatasetProviderRegistry, ModelAdapterRegistry, MetricRegistry, TaskKindRegistry
]:
    registries = PluginRegistries(
        DatasetProviderRegistry(), ModelAdapterRegistry(), MetricRegistry(), TaskKindRegistry()
    )
    register_plugins(registries)
    return registries.datasets, registries.models, registries.metrics, registries.tasks


def classification_config(
    output_uri: str = "benchmark-results", *, persist: bool = True
) -> BenchmarkSuiteConfig:
    return BenchmarkSuiteConfig(
        task_kind="classification",
        datasets=(DatasetSpec("toy-classification", PluginSpec("toy.classification")),),
        models=(ModelSpec("majority", PluginSpec("toy.majority")),),
        metrics=(MetricSpec("accuracy", PluginSpec("accuracy")),),
        artifacts=ArtifactSpec(output_uri, persist=persist),
        run=RunSpec(run_name="toy-classification", primary_metric="accuracy"),
    )


def forecasting_config(
    output_uri: str = "benchmark-results", *, persist: bool = True
) -> BenchmarkSuiteConfig:
    return BenchmarkSuiteConfig(
        task_kind="forecasting",
        datasets=(DatasetSpec("toy-forecasting", PluginSpec("toy.forecasting")),),
        models=(ModelSpec("last-value", PluginSpec("toy.last_value")),),
        metrics=(MetricSpec("mae", PluginSpec("mae")),),
        artifacts=ArtifactSpec(output_uri, persist=persist),
        run=RunSpec(run_name="toy-forecasting", primary_metric="mae"),
    )


def register_presets(presets: PresetRegistry) -> None:
    presets.register(
        "toy.classification",
        lambda options: classification_config(str(options.get("output_uri", "benchmark-results"))),
    )
    presets.register(
        "toy.forecasting",
        lambda options: forecasting_config(str(options.get("output_uri", "benchmark-results"))),
    )
