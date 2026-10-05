# Extension points

```text
config -> registered plugin contracts -> orchestrator -> artifacts -> compare
                                      BMF-102       BMF-106      BMF-108
```

BMF-101 defines the dataset, model, metric, and task extension points. BMF-102 keeps
those contracts and adds optional progress, resume, and error-artifact integration
points around suite execution. This document describes extension contracts; the
orchestrator lifecycle and execution policies are documented in
[`execution.md`](execution.md).

## Extension catalog

| Extension | Public contract | Integration surface | Introduced |
|---|---|---|---|
| Dataset | `DatasetProvider` | `DatasetProviderRegistry` | BMF-103 |
| Model | `ModelAdapter` | `ModelAdapterRegistry` | BMF-104 |
| Metric | `Metric` | `Registry[Metric]` | BMF-101 |
| Task kind | `TaskAdapter` | `TaskKindRegistry` | BMF-101 |
| Progress | `ProgressHook` | Optional `run_suite` argument | BMF-102 |
| Resume | `ResumeStore` | Optional `run_suite` argument | BMF-102 |
| Error artifact | `ErrorArtifactSink` | Optional `run_suite` argument | BMF-102 |


The current API has specialized registries for datasets and models, plus two uses
of the generic registry:

| Extension | Current registry | Current responsibility | Future work |
|---|---|---|---|
| Dataset | `DatasetProviderRegistry` | Provider name resolution and opaque provider options | BMF-103 implemented |
| Model | `ModelAdapterRegistry` | Adapter name resolution and opaque adapter options | BMF-104 implemented |
| Metric | `Registry[Metric]` | BMF-101 defines only the metric contract | BMF-105 adds `MetricRegistry` |
| Task kind | `TaskKindRegistry` | An extensible task-kind registry is an explicit BMF-101 requirement | Already introduced by BMF-101 |

This temporary API asymmetry is not a conceptual difference between the four plugin
types. BMF-105 will complete the symmetric public surface by adding
`MetricRegistry`:

```python
datasets = DatasetProviderRegistry()
models = ModelAdapterRegistry()
metrics = MetricRegistry()
tasks = TaskKindRegistry()
```

The specialized registries reuse `Registry[T]`; they do not replace its common
name-to-factory behavior.

## Generic registration

`Registry[T]` maps a stable, namespaced string to a factory. A factory receives
immutable `ReadonlyJSONObject` options and returns one Protocol implementation.

```python
from roast.plugins.registry import (
    DatasetProviderRegistry,
    ModelAdapterRegistry,
    Registry,
    TaskKindRegistry,
)

datasets = DatasetProviderRegistry()
models = ModelAdapterRegistry()
metrics = Registry("metric")
tasks = TaskKindRegistry()

datasets.register("example.dataset", dataset_factory)
models.register("example.model", model_factory)
metrics.register("example.metric", metric_factory)
tasks.register("example.custom_task", task_factory)
```

Duplicate names are rejected. Looking up an unknown name reports the names already
registered in that registry. Static typing and plugin contract tests validate the
factory result; the generic registry does not pretend to verify full Python method
semantics at runtime.

## DatasetProvider

```python
class DatasetProvider(Protocol):
    def load(self, spec: DatasetSpec) -> Iterable[ItemRecord]: ...
```

`ItemRecord.payload`, `target`, and `metadata` are task-neutral and JSON-friendly.
The provider owns interpretation of `PluginSpec.options`. ROAST passes those options
to the registered factory as an immutable mapping, then passes the complete
`DatasetSpec` to the provider's `load()` method.

### Register a provider with the Python API

A third-party package can implement and register a provider without modifying ROAST:

```python
from collections.abc import Iterable

from roast.core.config import DatasetSpec
from roast.core.records import ItemRecord
from roast.core.schema import ReadonlyJSONObject
from roast.plugins.registry import DatasetProviderRegistry


class InlineDatasetProvider:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        values = options.get("values", ())
        self._values = tuple(values) if isinstance(values, tuple) else ()

    def load(self, spec: DatasetSpec) -> Iterable[ItemRecord]:
        for index, value in enumerate(self._values):
            yield ItemRecord(
                item_id=f"item-{index}",
                dataset_id=spec.dataset_id,
                payload=value,
                target=value,
            )


datasets = DatasetProviderRegistry()
datasets.register("example.inline", InlineDatasetProvider)
```

Select the provider by its registered name and pass provider-owned options through
`PluginSpec`:

```python
from roast.core.config import DatasetSpec, PluginSpec

dataset = DatasetSpec(
    dataset_id="tiny",
    provider=PluginSpec(
        name="example.inline",
        options={"values": [1, 2, 3]},
    ),
)
```

Pass this `DatasetProviderRegistry` in `PluginRegistries` when calling `run_suite`.
The complete executable example is available in
[`examples/custom_plugins.py`](../examples/custom_plugins.py).

### Installable plugin discovery

ROAST does not currently discover dataset providers from Python package entry points.
In particular, declaring a `bmf.datasets` entry-point group does not register a
provider automatically. Applications must import the third-party package and call
`DatasetProviderRegistry.register()` explicitly, as shown above. This keeps plugin
loading and registration order under application control.

## ModelAdapter

```python
class ModelAdapter(Protocol):
    def availability(self) -> Availability: ...
```

The base adapter intentionally does not require `fit()` or `predict()`. Those shapes
are not universal. A task plugin declares its own structural capability, such as a
classifier with `fit/predict` or a forecaster with `forecast`, while still exposing
the common availability contract.

Availability gives the execution layer a task-neutral readiness signal. The
task-specific protocol determines the actual operation shape, such as
`predict_number()`, `predict()`, or `forecast()`.

### Register an adapter with the Python API

A third-party model package can implement the common availability contract and a
capability required by its selected task kind. Register its class or factory under
a stable name; no ROAST source changes are required:

```python
from roast.core.events import Availability
from roast.core.records import ItemRecord
from roast.core.schema import ReadonlyJSONObject
from roast.plugins.registry import ModelAdapterRegistry


class ScaleModel:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        factor = options.get("factor", 1.0)
        self._factor = float(factor)

    def availability(self) -> Availability:
        return Availability(available=True)

    def predict_number(self, item: ItemRecord) -> float:
        return float(item.payload) * self._factor


models = ModelAdapterRegistry()
models.register("example.scale", ScaleModel)
```

Select the registered adapter through `ModelSpec`. Adapter options remain owned by
the third-party factory:

```python
from roast.core.config import ModelSpec, PluginSpec

model = ModelSpec(
    model_id="double",
    adapter=PluginSpec(
        name="example.scale",
        options={"factor": 2},
    ),
    tags=("reference",),
)
```

Pass this `ModelAdapterRegistry` in `PluginRegistries` when calling `run_suite`.
The complete executable example is available in
[`examples/custom_plugins.py`](../examples/custom_plugins.py).

### Availability behavior

Every model adapter returns an `Availability` value before item execution. ROAST
uses one task-neutral mapping when `available` is false:

| `ModelSpec.optional` | Run status |
|---|---|
| `True` | `skipped` |
| `False` | `not_available` |

The adapter should put a human-readable explanation in `Availability.reason`.
Exceptions raised by the factory or `availability()` are recorded as failures, not
as unavailable models.

### Optional dependencies and lazy factories

Registration accepts any callable with the same shape as a model constructor. A
plugin can therefore defer an optional import until ROAST actually creates the
selected adapter:

```python
from roast.core.schema import ReadonlyJSONObject


def sklearn_factory(options: ReadonlyJSONObject):
    from my_sklearn_plugin import SklearnAdapter

    return SklearnAdapter(options)


models.register("example.sklearn", sklearn_factory)
```

Keep optional imports inside the factory so importing the plugin registration
module does not require every supported model library to be installed.

## Metric

```python
class Metric(Protocol):
    def compute(self, value: MetricInput) -> float: ...
```

`MetricInput` exposes truth, prediction, the source item, the selected `MetricSpec`,
and an explicit context mapping. The context leaves room for seasonality, anomaly
windows, weights, and similar inputs without hidden globals. Metric direction,
task compatibility, aliases, and the specialized registry belong to BMF-105.

## TaskAdapter

Task kinds use arbitrary registered strings rather than a closed enum:

```python
class TaskAdapter(Protocol):
    def execute_item(
        self,
        item: ItemRecord,
        model: ModelAdapter,
        context: ItemExecutionContext,
    ) -> PredictionOutput: ...
```

`TaskAdapter` defines one item's task-specific model invocation and output. Its
extension boundary deliberately excludes suite-level concerns such as iteration,
record assembly, checkpoints, and artifact persistence.

The suite config selects the registered implementation using `task_kind` and passes
opaque JSON `task_options` to its factory.

See [`examples/custom_plugins.py`](../examples/custom_plugins.py) for a complete
definition of all four mandatory extension types. It includes a consumer-owned
`NumericModel` capability and requires no changes to ROAST source.

## BMF-102 lifecycle extension points

The BMF-102 hooks are optional structural protocols. Consumers implement only the
capabilities they need and pass those implementations to `run_suite`.

`ProgressHook` consumes versioned `ProgressEvent` values:

```python
class ProgressHook(Protocol):
    def on_event(self, event: ProgressEvent) -> None: ...
```

`ResumeStore` exposes JSON checkpoint state:

```python
class ResumeStore(Protocol):
    def load(self, run_id: str) -> JSONObject | None: ...
    def save(self, run_id: str, state: ReadonlyJSONObject) -> None: ...
```

`ErrorArtifactSink` persists the aggregated error records and returns the artifact
descriptor contributed to the result:

```python
class ErrorArtifactSink(Protocol):
    def persist_errors(
        self,
        run_id: str,
        errors: tuple[ExecutionError, ...],
        spec: ArtifactSpec,
    ) -> ArtifactRecord: ...
```

These contracts do not prescribe logging backends, checkpoint storage, filenames,
or URI layouts. Their invocation semantics and related policies are defined in
[`execution.md`](execution.md). BMF-106 will define a portable, crash-safe on-disk
checkpoint and artifact layout.

## Config, artifacts, and schema versions

`BenchmarkSuiteConfig` is the single root configuration. Dataset, model, and metric
specifications select plugins by registered names. `ArtifactSpec` is declarative;
its `output_uri`, `persist`, and opaque options are passed to persistence extension
points without prescribing a storage implementation.

Every serialized public config, record, result, event, availability value, artifact
record, and artifact manifest carries `schema_version: 1`. Readers reject a missing
version, a value with the wrong JSON type, and an unsupported version. No implicit
schema migration is performed.

Public values serialize to JSON nulls, booleans, finite numbers, strings, arrays,
and objects with string keys. Immutable config arrays may be tuples in memory and
immutable objects may be mappings; `to_dict()` and `dumps()` convert them to ordinary
JSON arrays and objects.
