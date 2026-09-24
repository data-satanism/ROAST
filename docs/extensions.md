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
| Dataset | `DatasetProvider` | `Registry[DatasetProvider]` | BMF-101 |
| Model | `ModelAdapter` | `Registry[ModelAdapter]` | BMF-101 |
| Metric | `Metric` | `Registry[Metric]` | BMF-101 |
| Task kind | `TaskAdapter` | `TaskKindRegistry` | BMF-101 |
| Progress | `ProgressHook` | Optional `run_suite` argument | BMF-102 |
| Resume | `ResumeStore` | Optional `run_suite` argument | BMF-102 |
| Error artifact | `ErrorArtifactSink` | Optional `run_suite` argument | BMF-102 |


The current API has one specialized registry and three uses of the generic
registry:

| Extension | Current registry | Current responsibility | Future work |
|---|---|---|---|
| Dataset | `Registry[DatasetProvider]` | BMF-101 defines only the provider contract | BMF-103 adds `DatasetProviderRegistry` |
| Model | `Registry[ModelAdapter]` | BMF-101 defines only the adapter contract | BMF-104 adds `ModelAdapterRegistry` |
| Metric | `Registry[Metric]` | BMF-101 defines only the metric contract | BMF-105 adds `MetricRegistry` |
| Task kind | `TaskKindRegistry` | An extensible task-kind registry is an explicit BMF-101 requirement | Already introduced by BMF-101 |

This is a temporary API asymmetry, not a conceptual difference between the four
plugin types. BMF-103, BMF-104, and BMF-105 will provide a symmetric public
surface:

```python
datasets = DatasetProviderRegistry()
models = ModelAdapterRegistry()
metrics = MetricRegistry()
tasks = TaskKindRegistry()
```

The future specialized registries will reuse or extend `Registry[T]`; they will not
replace its common name-to-factory behavior.

## Generic registration

`Registry[T]` maps a stable, namespaced string to a factory. A factory receives
immutable `ReadonlyJSONObject` options and returns one Protocol implementation.

```python
from roast.plugins.registry import Registry, TaskKindRegistry

datasets = Registry("dataset provider")
models = Registry("model adapter")
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
The provider owns interpretation of `PluginSpec.options`. Dataset discovery,
provider-specific registries, and installable provider discovery belong to BMF-103.

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
specialized model registry remains a BMF-104 concern.

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
