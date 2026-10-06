# ROAST

Rigorous Offline AutoML Stress Testing.

## Quickstart

This path connects your dataset and automl framework without modifying ROAST.

### 1. Install ROAST and AutoML framework

```shell
python -m pip install -e .
python -m pip install automl-framework
```

The ROAST base package does not install model frameworks or heavy data
dependencies. Keep those dependencies in your integration package, or load them
inside plugin factories when they are optional.

### 2. Create your plugin module

Copy `examples/third_party_template/` into your project, for example as
`automl_benchmark/`. Adapt `plugin.py` at four boundaries:

1. `TemplateDatasetProvider.load()` reads your files, database, or in-memory data
   and yields `ItemRecord` values.
2. `TemplateModelAdapter` wraps your framework and exposes the prediction method
   required by your task.
3. `TemplateTaskAdapter.execute_item()` passes one item to that model method and
   returns `PredictionOutput`.
4. `TemplateMetric.compute()` evaluates the prediction, or register an existing
   standard metric instead.

Change the `template.*` registration names to names owned by your project. Keep
`register_plugins(registries)` as the module entry hook. Use
`register_presets(presets)` when you want a reusable suite configuration.

### 3. Register and inspect your plugins

Make your project importable, then pass its module path to the CLI:

```shell
python -m pip install -e /path/to/your-project
roast plugins list --plugin my_benchmark.plugin
```

The output lists the dataset providers, model adapters, metrics, task adapters,
and presets registered by your module. Unknown names fail before execution and
show the names that are available.

### 4. Describe and run your suite

Copy the template `manifest.json` beside your plugin. Select your registered
preset, or replace it with an inline suite configuration. Set `output_uri` to the
artifact directory you want to keep.

Resolve the manifest without running models:

```shell
roast resolve-manifest --manifest my_benchmark/manifest.json --plugin my_benchmark.plugin
```

Then execute it. Run again after changing a model, dependency version, seed, or
configuration to create a comparison candidate:

```shell
roast run --manifest my_benchmark/manifest.json --plugin my_benchmark.plugin
roast run --manifest my_benchmark/manifest.json --plugin my_benchmark.plugin
```

### 5. Inspect the artifacts

Each run is stored under the manifest's `output_uri` using the versioned portable
layout:

```text
<output_uri>/
  _registry/run_registry.jsonl
  runs/<run-id>/
    run_metadata.json
    config.json
    checkpoint.json
    manifest.json
    records/runs.jsonl
    records/predictions.jsonl
    records/metrics.jsonl
```

The CLI output contains the generated `run_id`. Open the corresponding directory
to inspect the resolved configuration, predictions, metrics, checksums, and run
metadata. These files are JSON/JSONL and can be read without importing ROAST.

### 6. Compare runs

Load your artifact root and print stable multi-run leaderboard rows:

```shell
python -c "from roast import build_comparison_table, load_artifact_root; runs=load_artifact_root('your-results'); [print(row) for row in build_comparison_table(runs)]"
```

The resulting rows contain the run, model, metric, score, direction, observation
count, and deterministic rank. Your integration remains in your project: ROAST
source code does not need dataset- or framework-specific changes.
