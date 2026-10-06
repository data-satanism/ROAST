# Portable artifact layout

BMF-106 defines a solution-neutral, versioned directory contract. All JSON objects
carry `schema_version: 1`; JSONL files contain one independently parseable JSON
object per non-empty line and use UTF-8.

```text
<artifact-root>/
  _registry/run_registry.jsonl
  _registry/run_registry.parquet       # optional
  runs/<run-id>/
    run_metadata.json
    config.json
    items.jsonl
    items.parquet                       # optional
    records/runs.jsonl
    records/runs.parquet                # optional
    records/predictions.jsonl
    records/predictions.parquet         # optional
    records/metrics.jsonl
    records/metrics.parquet             # optional
    errors.jsonl
    errors.parquet                      # optional
    manifest.json
    checkpoint.json
```

Paths in `manifest.json` and the run registry use `/` separators and are relative to
the containing run directory or artifact root. No filename or required metadata
field contains a solution, model-library, or consumer-package name.

## Versioning and JSON rules

Every document and every JSONL record has `schema_version` with integer value `1`.
A reader must reject a missing version, a non-integer version, or a version it does
not support. Values are strict JSON: null, booleans, finite numbers, strings,
arrays, and objects with string keys. JSONL readers may ignore empty lines.

## Root documents

### `run_metadata.json`

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer | Artifact schema version; currently `1` |
| `run_id` | string | Stable identifier of this run directory |
| `run_name` | string | Name from `RunSpec.run_name` |
| `task_kind` | string | Registered task-kind name |
| `state` | string | `running`, `failed`, `completed`, or `completed_with_errors` |
| `updated_at` | string | UTC timestamp serialized in ISO 8601 form |
| `counts` | object | Integer counts for `items`, `runs`, `predictions`, `metrics`, and `errors` |

### `config.json`

This is a serialized `BenchmarkSuiteConfig`. Its top-level fields are
`schema_version`, `task_kind`, `datasets`, `models`, `metrics`, `artifacts`, `run`,
and `task_options`. Plugin-specific options remain JSON values owned by the selected
plugin.

### `manifest.json`

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer | Artifact schema version; currently `1` |
| `run_id` | string | Run described by the manifest |
| `files` | array | Entries for portable interchange files |

Each `files` entry contains `path`, `media_type`, and the lowercase hexadecimal
`sha256` digest of the exact file bytes. The manifest excludes itself and the
internal `checkpoint.json`.

### `checkpoint.json`

This is a complete serialized `BenchmarkResult` used internally for resume. Its
top-level fields are `schema_version`, `run_id`, `task_kind`, `config`, `items`,
`runs`, `predictions`, `metrics`, `artifact_manifest`, and `metadata`. Portable
consumers should normally read the interchange files rather than this checkpoint.

## JSONL record schemas

Every row includes `schema_version: 1`.

| File | Record | Fields in addition to `schema_version` |
|---|---|---|
| `items.jsonl` | `ItemRecord` | `item_id`, `dataset_id`, `payload`, `target`, `metadata` |
| `records/runs.jsonl` | `RunRecord` | `record_id`, `run_id`, `dataset_id`, `model_id`, `item_id`, `status`, `message`, `started_at`, `finished_at`, `metadata` |
| `records/predictions.jsonl` | `PredictionRecord` | `record_id`, `run_id`, `dataset_id`, `model_id`, `item_id`, `prediction`, `truth`, `status`, `coordinates`, `metadata` |
| `records/metrics.jsonl` | `MetricRecord` | `record_id`, `run_id`, `dataset_id`, `model_id`, `item_id`, `metric_id`, `value`, `status`, `coordinates`, `metadata` |
| `errors.jsonl` | `ExecutionError` | `error_id`, `run_id`, `stage`, `exception_type`, `message`, `dataset_id`, `model_id`, `item_id`, `metric_id`, `traceback` |

`status` is one of `pending`, `running`, `success`, `failed`, `skipped`, or
`not_available`. Nullable fields are serialized as JSON `null`. Metric values are
finite numbers or null; metric metadata contains the canonical `registered_name`
and ranking `direction` (`minimize` or `maximize`).

## Run registry

`_registry/run_registry.jsonl` contains one row per run:

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer | Artifact schema version; currently `1` |
| `run_id` | string | Unique run identifier |
| `run_name` | string | Configured run name |
| `task_kind` | string | Registered task-kind name |
| `state` | string | Current run state |
| `uri` | string | Relative path to `run_metadata.json` |
| `updated_at` | string | UTC update timestamp |

Updating a run replaces its registry row instead of appending duplicates.

## Atomic incremental persistence

`FileSystemRunStore` implements both `ResumeStore` and `ErrorArtifactSink`. Every
file is written to a temporary sibling, flushed, and atomically replaced. Record
files are materialized before the checkpoint, so a readable checkpoint never
points beyond the portable records visible to other tools.

```python
from dataclasses import replace
from roast.execution.persistence import FileSystemRunStore

store = FileSystemRunStore.from_artifact_spec(config.artifacts)
config = replace(config, run=replace(config.run, resume_enabled=True))
result = run_suite(config, registries, resume_store=store)

resumed_config = replace(
    config,
    run=replace(config.run, resume_run_id=result.run_id),
)
result = run_suite(resumed_config, registries, resume_store=store)
```

For a run that does not enable checkpoints, call `store.persist_result(result)` to
write the same layout once at completion. Consumers need only a JSON/JSONL parser;
they do not need ROAST installed.

## Optional Parquet mirrors

JSON and JSONL remain the normative, dependency-free schema. To additionally write
Parquet mirrors, install the optional extra and enable the artifact option:

```shell
pip install "roast[parquet]"
# or: uv sync --extra parquet
```

```python
from roast.core.config import ArtifactSpec
from roast.execution.persistence import FileSystemRunStore

artifacts = ArtifactSpec(
    output_uri="benchmark-results",
    options={"parquet": True},
)
store = FileSystemRunStore.from_artifact_spec(artifacts)
```

The store writes `.parquet` beside every `.jsonl` stream and writes
`_registry/run_registry.parquet` beside the JSONL registry. Parquet run files are
listed in `manifest.json` with media type `application/vnd.apache.parquet` and
SHA-256 digests. Their schema metadata contains:

- `roast.schema_version`: the BMF schema version as ASCII;
- `roast.json_columns`: a JSON array naming columns encoded as canonical JSON
  strings.

Identifiers, statuses, timestamps, metric values, and schema versions remain native
Parquet scalar columns. Potentially nested or heterogeneous fields such as payload,
target, prediction, coordinates, and metadata are canonical JSON strings. Empty
streams still produce valid zero-row Parquet files with the documented column
names.

`pyarrow` is imported lazily only when Parquet output is enabled. Without the extra,
normal JSON persistence and package import continue to work; requesting Parquet
raises an actionable dependency error before any run files are replaced.

## Reading without ROAST

A dashboard, CI job, or paper pipeline can consume the layout with only the Python
standard library:

```python
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


run_dir = Path("benchmark-results/runs/<run-id>")
metadata = json.loads((run_dir / "run_metadata.json").read_text("utf-8"))
if metadata.get("schema_version") != 1:
    raise ValueError("unsupported artifact schema")

metrics = read_jsonl(run_dir / "records/metrics.jsonl")
for record in metrics:
    if record.get("schema_version") != 1:
        raise ValueError("unsupported metric-record schema")
```

`tests/unit/execution/test_persistence.py` builds a generic fixture run, parses the
documents and every record stream with `json`, validates required fields and
versions, verifies manifest checksums, and resumes the run using only BMF APIs.

JSON is the normative interchange format in schema version 1. Parquet is an optional
analytical mirror and may always be regenerated from the JSONL streams.
