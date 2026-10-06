from __future__ import annotations

from collections.abc import Iterable

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
from roast.plugins.registry import MetricDirection, PresetRegistry
from roast.protocols.metric import MetricInput
from roast.protocols.model import ModelAdapter
from roast.protocols.task import ItemExecutionContext, PredictionOutput


class TemplateDatasetProvider:
    """Replace this provider with loading code for your dataset."""

    def __init__(self, options: ReadonlyJSONObject) -> None:
        values = options.get("values", (1, 2, 3))
        if not isinstance(values, tuple):
            raise TypeError("values must be an array")
        self.values = values

    def load(self, spec: DatasetSpec) -> Iterable[ItemRecord]:
        for index, value in enumerate(self.values):
            yield ItemRecord(
                item_id=f"item-{index}",
                dataset_id=spec.dataset_id,
                payload=value,
                target=float(value) * 2,
            )


class TemplateModelAdapter:
    """Replace predict_value() with the capability required by your task."""

    def __init__(self, options: ReadonlyJSONObject) -> None:
        self.factor = float(options.get("factor", 1))

    def availability(self) -> Availability:
        return Availability(available=True)

    def predict_value(self, item: ItemRecord) -> float:
        return float(item.payload) * self.factor


class TemplateMetric:
    """A dependency-free metric receiving explicit prediction context."""

    def __init__(self, options: ReadonlyJSONObject) -> None:
        self.options = options

    def compute(self, value: MetricInput) -> float:
        return abs(float(value.truth) - float(value.prediction))


class TemplateTaskAdapter:
    """Connect the generic execution loop to the model capability."""

    def __init__(self, options: ReadonlyJSONObject) -> None:
        self.options = options

    def execute_item(
        self,
        item: ItemRecord,
        model: ModelAdapter,
        context: ItemExecutionContext,
    ) -> PredictionOutput:
        predict = getattr(model, "predict_value", None)
        if not callable(predict):
            raise TypeError("template task requires predict_value(item)")
        return PredictionOutput(
            prediction=predict(item),
            truth=item.target,
            metadata={"task_kind": context.task_kind},
        )


def register_plugins(registries: PluginRegistries) -> None:
    """Register every extension under stable, consumer-owned names."""

    registries.datasets.register("template.dataset", TemplateDatasetProvider)
    registries.models.register("template.model", TemplateModelAdapter)
    registries.metrics.register(
        "template.absolute_error",
        TemplateMetric,
        direction=MetricDirection.MINIMIZE,
        task_kinds=("template.task",),
    )
    registries.tasks.register("template.task", TemplateTaskAdapter)


def build_config(
    output_uri: str = "template-results",
    *,
    persist: bool = True,
) -> BenchmarkSuiteConfig:
    """Build the same suite selected by the accompanying manifest."""

    return BenchmarkSuiteConfig(
        task_kind="template.task",
        datasets=(
            DatasetSpec(
                "template-data",
                PluginSpec("template.dataset", {"values": [1, 2, 3]}),
            ),
        ),
        models=(
            ModelSpec("template-model", PluginSpec("template.model", {"factor": 2})),
        ),
        metrics=(
            MetricSpec("absolute_error", PluginSpec("template.absolute_error")),
        ),
        artifacts=ArtifactSpec(output_uri, persist=persist),
        run=RunSpec(run_name="third-party-template", primary_metric="absolute_error"),
    )


def register_presets(presets: PresetRegistry) -> None:
    """Make the template suite selectable by a declarative manifest."""

    presets.register(
        "template.demo",
        lambda options: build_config(
            str(options.get("output_uri", "template-results")),
            persist=bool(options.get("persist", True)),
        ),
    )
