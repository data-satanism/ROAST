# Third-party integration guide

This guide shows how to add datasets, models, metrics, and task semantics without
editing ROAST. The worked integration runs scikit-learn on a tiny CSV file using
[`examples/sklearn_csv/plugin.py`](../examples/sklearn_csv/plugin.py), and the
same code is exercised by the BMF-only test suite. A dependency-free starting
point is available in [`examples/third_party_template`](../examples/third_party_template).

## Choose your path

- **Python API** — construct registries and configs in application code, call
  `run_suite()`, and consume `BenchmarkResult` directly.
- **CLI** — load an importable plugin module explicitly and run reproducible jobs
  in a terminal or CI environment.
- **Manifest** — keep the selected registered names and options in versioned JSON
  or YAML; use a preset when the plugin package owns the base configuration.

All three paths resolve the same registered names and execute the same
orchestrator.

## Mental model

```text
DatasetProviderRegistry       ModelAdapterRegistry
          |                           |
          v                           v
 DatasetSpec -> ItemRecord -> TaskAdapter -> PredictionOutput
                                      |
                                      v
                              MetricRegistry
                                      |
                                      v
 config -> run_suite -> BenchmarkResult -> portable artifacts -> comparison
```

Core owns iteration, statuses, record identifiers, checkpoints, error capture, and
serialization. Plugins own only domain behavior. Dataset and plugin options are
immutable JSON mappings and remain opaque to core.

## 1. Dataset provider

A provider factory receives its registered options. Its `load()` method receives
the complete `DatasetSpec` and yields JSON-friendly `ItemRecord` values.

```python
from roast import DatasetSpec
from roast.core.records import ItemRecord

class CsvRows:
    def __init__(self, options):
        self.path = options["path"]

    def load(self, spec: DatasetSpec):
        # Parse your file here. Core does not choose paths or formats.
        yield ItemRecord("row-1", spec.dataset_id, payload=[1, 2], target="yes")

registries.datasets.register("acme.csv_rows", CsvRows)
```

Returned `dataset_id` values must match the selected `DatasetSpec`, and item IDs
must be unique inside a dataset. Unknown provider names fail before plugin code is
invoked and list registered providers.

## 2. Model adapter

Every model exposes task-neutral availability. Task-specific methods are structural
capabilities chosen by the task adapter.

```python
from roast.core.events import Availability

class MyClassifier:
    def __init__(self, options):
        self.threshold = options.get("threshold", 0.5)

    def availability(self):
        return Availability(True)

    def predict_label(self, payload):
        return "yes" if sum(payload) >= self.threshold else "no"

registries.models.register("acme.classifier", MyClassifier)
```

Import optional libraries inside the factory or constructor. Return
`Availability(False, reason)` when a dependency or resource is unavailable.
`ModelSpec.optional=True` maps this to `skipped`; a required model maps it to
`not_available`. Unexpected availability errors become `failed` records.

## 3. Metric

Metrics receive truth, prediction, source item, selected spec, and explicit context.
Registration declares ranking direction, compatible task kinds, and aliases.

```python
from roast import MetricDirection

class ExactMatch:
    def __init__(self, options):
        pass

    def compute(self, value):
        return float(value.truth == value.prediction)

registries.metrics.register(
    "acme.exact_match",
    ExactMatch,
    direction=MetricDirection.MAXIMIZE,
    task_kinds=("classification",),
    aliases=("acme.exact_match@1",),
)
```

Accuracy, MAE, RMSE, and sMAPE are available from
`roast.standard_metric_registry()`. Advanced domain metrics belong in consumer
packages.

## 4. Task kind

The task adapter connects an item to a model capability for one item only. It does
not iterate datasets, calculate every configured metric, persist files, or assemble
results.

```python
from roast.protocols.task import PredictionOutput

class ClassificationTask:
    def __init__(self, options):
        pass

    def execute_item(self, item, model, context):
        prediction = model.predict_label(item.payload)
        return PredictionOutput(prediction=prediction, truth=item.target)

registries.tasks.register("classification", ClassificationTask)
```

Raise `SkipItem` for a deliberate skip or `ItemNotAvailable` when the individual
work unit cannot be evaluated. Other exceptions are captured according to
`ExecutionPolicy`.

## Worked example: scikit-learn and CSV

The example CSV has `split`, two numeric feature columns, and `label`. Its plugin:

- reads the CSV with the standard library and yields one item per test row;
- carries the training rows in the JSON-compatible item payload;
- lazily imports and fits `sklearn.linear_model.LogisticRegression`;
- connects that capability through a classification task adapter;
- registers accuracy with `MAXIMIZE` direction;
- persists predictions and metrics through the standard artifact store.

Install the example dependency without adding it to ROAST core:

```shell
python -m pip install -e ".[sklearn-example]"
```

## Complete Python path

The checked-in sklearn plugin implements the provider, model, metric, task,
registration hook, and config used below:

```python
from roast import (
    FileSystemRunStore,
    PluginRegistries,
    build_leaderboard,
    load_artifact_root,
    run_suite,
)
from roast.plugins.registry import (
    DatasetProviderRegistry,
    MetricRegistry,
    ModelAdapterRegistry,
    TaskKindRegistry,
)
from examples.sklearn_csv.plugin import build_config, register_plugins

registries = PluginRegistries(
    DatasetProviderRegistry(),
    ModelAdapterRegistry(),
    MetricRegistry(),
    TaskKindRegistry(),
)
register_plugins(registries)
config = build_config(
    "examples/sklearn_csv/tiny_classification.csv",
    "sklearn-csv-results",
)
result = run_suite(config, registries)
FileSystemRunStore(config.artifacts.output_uri).persist_result(result)

reloaded = load_artifact_root("sklearn-csv-results")[0]
print(build_leaderboard(reloaded))
```

Replace the example CSV schema and sklearn adapter with your dataset and framework,
then change the `example.*` registration names to your package namespace. The
orchestration and persistence code above does not change.

## Manifest and CLI path

`examples/sklearn_csv/manifest.json` selects the same plugins through a
consumer preset:

```shell
roast plugins list --plugin examples.sklearn_csv.plugin
roast resolve-manifest --manifest examples/sklearn_csv/manifest.json --plugin examples.sklearn_csv.plugin
roast run --manifest examples/sklearn_csv/manifest.json --plugin examples.sklearn_csv.plugin
```

Use an inline `suite` manifest when no preset is appropriate. Both shapes require
`format: roast_manifest@1` and `schema_version: 1`. See
[`manifests.md`](manifests.md) for their exact structure.

## Packaging a plugin distribution

A plugin distribution is an ordinary Python package. Keep framework dependencies
in that package rather than ROAST core, and expose one registration function:

```python
def register_plugins(registries):
    registries.datasets.register("acme.csv_rows", CsvRows)
    registries.models.register("acme.classifier", MyClassifier)
    registries.metrics.register("acme.exact_match", ExactMatch)
    registries.tasks.register("acme.classification", ClassificationTask)

def register_presets(presets):
    presets.register("acme.small", build_small_config)
```

Users pass the module to `--plugin acme_roast`. ROAST intentionally does not import
arbitrary installed packages automatically; this keeps startup deterministic and
prevents one broken optional dependency from breaking unrelated runs.

Version registered names when behavior changes incompatibly, for example
`acme.metric@2`. Keep old factories registered while readers still need historical
manifests.

## Artifacts and comparison

`FileSystemRunStore` writes the versioned layout described in
[`artifacts.md`](artifacts.md). Dashboards and paper pipelines can read its JSON and
JSONL files without importing ROAST. Python consumers can use
`load_artifact_root`, `build_leaderboard`, `build_mean_ranks`,
`build_pairwise_deltas`, and `build_comparison_table`; see
[`comparison.md`](comparison.md).

## Common pitfalls

- **Optional dependency imported at module import time:** move it into a factory
  and report a clear `Availability(False, reason)` when unavailable.
- **Mutable or non-JSON options:** plugin options, payloads, targets, predictions,
  metadata, and context must contain finite JSON values only.
- **Provider returns a foreign dataset ID:** copy `spec.dataset_id` into every item.
- **Hidden metric context:** put seasonality, weights, or anomaly windows in
  `MetricInput.context` or explicit options.
- **Wrong direction:** losses/errors normally use `MINIMIZE`; scores such as
  accuracy normally use `MAXIMIZE`.
- **Task mismatch:** declare `task_kinds` during metric registration so an invalid
  suite fails before execution.
- **Eager path defaults:** require paths through provider options. Core and reusable
  plugin packages should not assume repository-relative data directories.
- **Resume changed config or data:** resume validates config and provider-produced
  items. Start a new run ID for intentional changes.
- **Schema edits without a version plan:** serialized public changes require an
  explicit schema-version decision and updated fixtures.

## FAQ

### Can I keep existing result folders?

Yes. Write a one-time converter that emits the BMF-106 layout, or keep the legacy
reader in your consumer package. Do not add solution-specific filename heuristics
to core. Once converted, generic ingestion and comparison APIs work normally.

### How do I version plugins?

Treat registered names as stable API. Use an alias for equivalent names and a new
versioned name when semantics change. Artifact records store the canonical metric
name and direction, preserving ranking behavior.

### Must users install optional model libraries?

No. Put those dependencies in plugin extras and import them lazily. Other datasets,
models, and metrics remain usable when an optional library is absent.

### Where should custom display names live?

In showcase manifests or consumer presentation code. Core comparison uses identity
names and never scans for product markers.
