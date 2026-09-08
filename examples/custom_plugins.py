from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

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
from roast.plugins.registry import Registry, TaskKindRegistry
from roast.protocols.dataset import DatasetProvider
from roast.protocols.metric import Metric, MetricInput
from roast.protocols.model import ModelAdapter
from roast.protocols.task import ItemExecutionContext, PredictionOutput
from roast.serialization.json import dumps


class InlineNumbers:
    """Provide numeric benchmark items from plugin options.

    Args:
        options: Immutable options containing numeric values and an optional
            target multiplier.
    """

    def __init__(self, options: ReadonlyJSONObject) -> None:
        values = options.get("values", ())
        self._values = tuple(values) if isinstance(values, tuple) else ()
        factor = options.get("target_factor", 1.0)
        self._target_factor = float(factor) if isinstance(factor, (int, float)) else 1.0

    def load(self, spec: DatasetSpec) -> Iterable[ItemRecord]:
        return tuple(
            ItemRecord(
                item_id=f"number-{index}",
                dataset_id=spec.dataset_id,
                payload=value,
                target=float(value) * self._target_factor,
            )
            for index, value in enumerate(self._values)
        )


class ScaleModel:
    """Predict numeric values by applying a configured scale factor.

    Args:
        options: Immutable options containing an optional scale factor.
    """

    def __init__(self, options: ReadonlyJSONObject) -> None:
        factor = options.get("factor", 1.0)
        self._factor = float(factor) if isinstance(factor, (int, float)) else 1.0

    def availability(self) -> Availability:
        return Availability(available=True)

    def predict_number(self, item: ItemRecord) -> float:
        return float(item.payload) * self._factor


@runtime_checkable
class NumericModel(ModelAdapter, Protocol):
    """Define the model capability required by the numeric task adapter."""

    def predict_number(self, item: ItemRecord) -> float: ...


class AbsoluteError:
    """Compute absolute error for a numeric prediction.

    Args:
        options: Immutable plugin options reserved for future customization.
    """

    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def compute(self, value: MetricInput) -> float:
        return abs(float(value.truth) - float(value.prediction))


class NumericPredictionTask:
    """Execute numeric prediction semantics for a single item.

    Args:
        options: Immutable task options retained by the adapter.
    """

    def __init__(self, options: ReadonlyJSONObject) -> None:
        self.options = options

    def execute_item(
        self,
        item: ItemRecord,
        model: ModelAdapter,
        context: ItemExecutionContext,
    ) -> PredictionOutput:
        if not isinstance(model, NumericModel):
            raise TypeError("numeric prediction requires the NumericModel capability")
        return PredictionOutput(
            prediction=model.predict_number(item),
            truth=item.target,
            metadata={"task_kind": context.task_kind},
        )


def build_registries() -> tuple[
    Registry[DatasetProvider],
    Registry[ModelAdapter],
    Registry[Metric],
    TaskKindRegistry,
]:
    """Build registries populated with the example plugin factories.

    Returns:
        Dataset, model, metric, and task registries for the example contracts.
    """

    datasets: Registry[DatasetProvider] = Registry("dataset provider")
    models: Registry[ModelAdapter] = Registry("model adapter")
    metrics: Registry[Metric] = Registry("metric")
    tasks = TaskKindRegistry()

    datasets.register("example.inline_numbers", InlineNumbers)
    models.register("example.scale", ScaleModel)
    metrics.register("example.absolute_error", AbsoluteError)
    tasks.register("example.numeric_prediction", NumericPredictionTask)
    return datasets, models, metrics, tasks


def build_config(output_uri: str = "benchmark-results") -> BenchmarkSuiteConfig:
    """Build a serializable suite configuration for the example plugins.

    Args:
        output_uri: Declarative destination for future artifact persistence.

    Returns:
        A suite configuration that selects plugins only by registered names.
    """

    return BenchmarkSuiteConfig(
        task_kind="example.numeric_prediction",
        task_options={"label": "third-party contract example"},
        datasets=(
            DatasetSpec(
                dataset_id="tiny",
                provider=PluginSpec(
                    "example.inline_numbers",
                    {"values": [1, 2, 3], "target_factor": 2},
                ),
            ),
        ),
        models=(
            ModelSpec(
                model_id="double",
                adapter=PluginSpec("example.scale", {"factor": 2}),
            ),
        ),
        metrics=(
            MetricSpec(
                metric_id="absolute_error",
                metric=PluginSpec("example.absolute_error"),
            ),
        ),
        artifacts=ArtifactSpec(output_uri=output_uri, persist=False),
        run=RunSpec(run_name="custom", primary_metric="absolute_error"),
    )


def main() -> None:
    """Print the contract-only example configuration as JSON."""

    build_registries()
    print(dumps(build_config()))


if __name__ == "__main__":
    main()
