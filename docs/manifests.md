# Manifests, presets, and CLI

ROAST manifests select datasets, models, metrics, and task adapters only by
registered plugin names. Core does not contain dataset-family or model-library
defaults.

## Installation and CLI

Install the base package for JSON manifests. YAML is optional:

```shell
pip install .
pip install ".[yaml]"
```

The installation exposes the `roast` command:

```shell
roast plugins list --plugin examples.custom_plugins
roast resolve-manifest --manifest examples/custom_manifest.json --plugin examples.custom_plugins
roast run --manifest examples/custom_manifest.json --plugin examples.custom_plugins
```

`--plugin` accepts an importable Python module. The module must define either
`register_plugins(registries)` or `build_registries()`, and may define
`register_presets(presets)`. Repeat `--plugin` to combine independent plugin
modules. Imports are explicit, so an optional plugin dependency is loaded only
when its module is requested.

`plugins list` prints registered dataset, model, metric, task, and preset names.
`resolve-manifest` validates and resolves the manifest, then prints the complete
`BenchmarkSuiteConfig` without running it. `run` resolves the same configuration
and executes it.

## Versioned manifest envelope

Every manifest is a JSON or YAML object with these fields:

| Field | Required | Meaning |
|---|---:|---|
| `format` | yes | Must be `roast_manifest@1` |
| `schema_version` | yes | Must be `1` |
| `suite` | one of | Complete inline suite configuration |
| `preset` | one of | Registered preset name |
| `preset_options` | no | JSON object passed opaquely to the preset factory |
| `overrides` | no | Recursive overrides applied to a resolved preset |

Exactly one of `suite` and `preset` is required. `overrides` is valid only with
`preset`. Unknown fields, unsupported versions, malformed JSON/YAML, unreadable
files, and unknown registered names fail with an error identifying the invalid
value. Registry errors also list available names.

## Inline suite schema

The runnable example is [`examples/custom_manifest.json`](../examples/custom_manifest.json).
Its `suite` object has the following fields:

| Field | Type | Meaning |
|---|---|---|
| `task_kind` | string | Registered task-adapter name |
| `task_options` | object | Opaque options owned by the task adapter |
| `datasets` | non-empty array | Dataset specifications |
| `models` | non-empty array | Model specifications |
| `metrics` | non-empty array | Metric specifications |
| `artifacts` | object | Output and persistence policy |
| `run` | object | Task-neutral execution options |
| `schema_version` | integer | Must be `1` |

Each dataset contains `dataset_id`, a `provider` plugin specification, optional
`metadata`, and `schema_version`. Each model contains `model_id`, an `adapter`
plugin specification, optional `tags`, `optional`, `metadata`, and
`schema_version`. Each metric contains `metric_id`, a `metric` plugin
specification, and `schema_version`.

A plugin specification contains:

```json
{
  "name": "registered.plugin.name",
  "options": {},
  "schema_version": 1
}
```

Plugin `options`, dataset/model `metadata`, task `task_options`, run `options`,
and artifact `options` are strict JSON objects. ROAST preserves them without
interpreting consumer-owned values.

`artifacts` contains `output_uri`, `persist`, `options`, and `schema_version`.
`run` supports `run_name`, `random_seed`, `primary_metric`, `resume_enabled`,
`resume_run_id`, `options`, and `schema_version`. `primary_metric`, when set,
must reference a configured `metric_id`; `resume_run_id` requires
`resume_enabled: true`.

## Presets and composition

Applications register their own presets:

```python
from roast.plugins.registry import PresetRegistry

presets = PresetRegistry()
presets.register("acme.tiny", build_tiny_config)
```

Factories receive immutable JSON `preset_options` and return a
`BenchmarkSuiteConfig`. Core defines no task-, dataset-, or model-specific preset
names.

A preset manifest can recursively override object fields after the factory has
returned its base configuration:

```json
{
  "format": "roast_manifest@1",
  "schema_version": 1,
  "preset": "example.tiny",
  "preset_options": {},
  "overrides": {
    "artifacts": {
      "output_uri": "benchmark-results",
      "persist": true
    },
    "run": {
      "run_name": "nightly"
    }
  }
}
```

Objects are merged recursively. Arrays and scalar values replace the preset
value. The resulting configuration is validated with the same versioned schema
as an inline suite, so an override cannot introduce an unknown or invalid field.

## Python API

Use `SuiteManifest.from_dict()` to validate an already-loaded object or
`load_manifest(path, presets)` to read and resolve JSON/YAML. Both return a
validated `BenchmarkSuiteConfig` through `SuiteManifest.resolve()`. The same
configuration can be passed to `run_suite()` with application-owned plugin
registries.
