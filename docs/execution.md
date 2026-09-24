# BMF-102 generic suite execution

The generic orchestrator resolves the four mandatory plugin kinds and owns the
task-neutral suite lifecycle:

```text
config + registries
        |
        v
load dataset items -> resolve models -> check availability
        |
        v
TaskAdapter.execute_item -> Metric.compute -> standard records
        |
        v
checkpoint + progress + aggregated errors -> BenchmarkResult
```

Task adapters own only one item's task-specific model invocation. They do not walk
the suite, build record identifiers, compute the configured metric set, checkpoint
state, persist errors, or assemble the result.

## Running a suite

```python
from roast.execution.orchestrator import PluginRegistries, run_suite

registries = PluginRegistries(
    datasets=datasets,
    models=models,
    metrics=metrics,
    tasks=tasks,
)

result = run_suite(config, registries)
```

`run_suite` resolves every `PluginSpec.name` through the corresponding registry.
Unknown names therefore fail with the registry's actionable list of available
names. Providers are visited in config order, their items remain in provider order,
and models remain in config order.

The lifecycle is driven entirely by registered contracts. It does not branch on
specific task kinds, model families, datasets, or benchmark names. A task adapter
owns only the fit/predict semantics for one item; dataset providers own item
loading, while the orchestrator owns iteration and result assembly.

For every item/model pair, the orchestrator creates a terminal `RunRecord`:

| Condition | Status |
|---|---|
| Task and all metrics complete | `success` |
| `SkipItem` is raised | `skipped` |
| `ItemNotAvailable` is raised | `not_available` |
| Optional model reports unavailable | `skipped` |
| Required model reports unavailable | `not_available` |
| Model availability, task, or metric raises | `failed` |

A failed metric also produces a failed `MetricRecord` with `value=None`. A task
failure cannot produce a prediction or metric record because no valid
`PredictionOutput` exists.

## Error policy and artifacts

`ExecutionPolicy` controls error handling:

```python
from roast.execution.policy import ExecutionPolicy

policy = ExecutionPolicy(
    fail_fast=False,
    include_traceback=False,
    persist_error_artifact=False,
    retry_failed_on_resume=True,
)
```

Captured failures are always serialized under `BenchmarkResult.metadata.errors` as
versioned `ExecutionError` objects. With `fail_fast=False`, independent item/model
pairs continue. With `fail_fast=True`, execution stops after the first failed pair
and raises `SuiteExecutionError`; its `partial_result` remains a valid
`BenchmarkResult`.

Unknown plugin names and invalid provider item records are configuration or contract
errors and raise directly. Exceptions raised by dataset provider factories or
loading, task factories, and metric factories are suite setup failures. They become
`ExecutionError` records with stages `dataset_factory`, `dataset_load`,
`task_factory`, or `metric_factory`, emit `suite_started` and `suite_failed`, and
raise `SuiteExecutionError` with a partial result. A provider that fails while
iterating may leave some items in that result. Setup failures are not checkpointed:
the next attempt must load the complete item list again.

ROAST does not impose an error filename or directory layout at this stage. To write
an error artifact, enable both `ArtifactSpec.persist` and
`ExecutionPolicy.persist_error_artifact`, then provide an `ErrorArtifactSink`:

```python
class MyErrorSink:
    def persist_errors(self, run_id, errors, spec):
        # Consumer-owned persistence and URI selection.
        return ArtifactRecord(
            artifact_id="errors",
            kind="execution_errors",
            uri="memory://run/errors",
            media_type="application/json",
        )
```

The returned `ArtifactRecord` is included in the result manifest. BMF-106 will
standardize the portable disk layout and incremental writers; BMF-102 only defines
the sink boundary and when it is invoked.
The sink must return `kind="execution_errors"`. On resume, the orchestrator drops
the previous error-artifact reference and writes a new one only when errors remain
and persistence is enabled. Removing a previously written file is the sink owner's
responsibility.

## Progress

Pass a `ProgressHook` to consume structured `ProgressEvent` values. The orchestrator
emits these stable event kinds:

- `suite_started`;
- `item_started`;
- `item_completed`;
- `item_resumed`;
- `suite_completed` or `suite_failed`.

Events contain completed and total item/model-pair counts plus dataset, model, item,
and status metadata where applicable. The orchestrator never prints directly, so a
consumer may implement console output, structured logging, or a remote reporter.

## Resume

Resume is enabled declaratively:

```python
RunSpec(
    run_name="experiment",
    resume_enabled=True,
    resume_run_id="experiment-existing-id",  # omit on the first run
)
```

A `ResumeStore` must be passed whenever resume is enabled. After every terminal
item/model outcome, the orchestrator saves a complete JSON-friendly
`BenchmarkResult` checkpoint. On a resumed call it verifies the task, datasets,
models, metrics, execution options, and provider-produced items before reusing
terminal records.

Successful, skipped, and unavailable pairs are not recomputed. Failed pairs are
retried by default; set `retry_failed_on_resume=False` to retain them instead.
The current store is consumer-owned and may be in-memory or file-backed. Portable
atomic persistence is intentionally deferred to BMF-106.

## Runnable example

[`examples/custom_plugins.py`](../examples/custom_plugins.py) defines a provider,
model capability, model adapter, metric, and task adapter, registers them, runs the
suite, and prints the resulting JSON. It imports only ROAST and Python standard
library modules.
