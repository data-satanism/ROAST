from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from hashlib import sha256
from importlib import import_module
import json
import os
from pathlib import Path
import tempfile
from typing import Any, cast
from urllib.parse import unquote, urlparse

from roast.core.config import ArtifactSpec
from roast.core.records import ArtifactRecord, BenchmarkResult
from roast.core.schema import (
    JSONObject,
    ReadonlyJSONObject,
    SCHEMA_VERSION,
    to_plain_data,
)
from roast.execution.errors import ExecutionError


RUNS_DIRECTORY = "runs"
REGISTRY_PATH = Path("_registry") / "run_registry.jsonl"
PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"

_PARQUET_STREAMS = {
    "items.jsonl": (
        ("item_id", "dataset_id", "payload", "target", "metadata", "schema_version"),
        ("payload", "target", "metadata"),
    ),
    "records/runs.jsonl": (
        (
            "record_id", "run_id", "dataset_id", "model_id", "item_id", "status",
            "message", "started_at", "finished_at", "metadata", "schema_version",
        ),
        ("metadata",),
    ),
    "records/predictions.jsonl": (
        (
            "record_id", "run_id", "dataset_id", "model_id", "item_id",
            "prediction", "truth", "status", "coordinates", "metadata",
            "schema_version",
        ),
        ("prediction", "truth", "coordinates", "metadata"),
    ),
    "records/metrics.jsonl": (
        (
            "record_id", "run_id", "dataset_id", "model_id", "item_id",
            "metric_id", "value", "status", "coordinates", "metadata",
            "schema_version",
        ),
        ("coordinates", "metadata"),
    ),
    "errors.jsonl": (
        (
            "error_id", "run_id", "stage", "exception_type", "message",
            "dataset_id", "model_id", "item_id", "metric_id", "traceback",
            "schema_version",
        ),
        (),
    ),
}

_REGISTRY_PARQUET_FIELDS = (
    "schema_version", "run_id", "run_name", "task_kind", "state", "uri",
    "updated_at",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_run_id(run_id: str) -> str:
    if (
        not isinstance(run_id, str)
        or not run_id.strip()
        or run_id in {".", ".."}
        or "/" in run_id
        or "\\" in run_id
    ):
        raise ValueError("run_id must be a non-empty portable path segment")
    return run_id


def _plain_root(value: str | os.PathLike[str]) -> Path:
    if isinstance(value, os.PathLike):
        return Path(value)
    if os.name == "nt" and (
        (len(value) >= 3 and value[1] == ":" and value[2] in "/\\")
        or value.startswith("\\\\")
    ):
        return Path(value)
    parsed = urlparse(value)
    if parsed.scheme and parsed.scheme != "file":
        raise ValueError("FileSystemRunStore supports paths and file:// URIs only")
    if parsed.scheme == "file":
        path = unquote(parsed.path)
        if parsed.netloc:
            path = f"//{parsed.netloc}{path}"
        if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return Path(path)
    return Path(value)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _jsonl_bytes(values: Iterable[object]) -> bytes:
    return b"".join(
        (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for value in values
    )


def _parquet_bytes(
    rows: Iterable[Mapping[str, object]],
    *,
    fields: tuple[str, ...],
    json_fields: tuple[str, ...] = (),
) -> bytes:
    try:
        pyarrow = import_module("pyarrow")
        parquet = import_module("pyarrow.parquet")
    except ModuleNotFoundError as error:
        if error.name == "pyarrow" or (error.name or "").startswith("pyarrow."):
            raise RuntimeError(
                "Parquet output requires the optional 'pyarrow' dependency; "
                "install ROAST with the 'parquet' extra"
            ) from error
        raise

    json_field_set = set(json_fields)
    normalized = []
    for row in rows:
        normalized.append(
            {
                field: (
                    json.dumps(
                        row.get(field),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if field in json_field_set
                    else row.get(field)
                )
                for field in fields
            }
        )
    table = (
        pyarrow.Table.from_pylist(normalized)
        if normalized
        else pyarrow.Table.from_pydict({field: [] for field in fields})
    )
    metadata = dict(table.schema.metadata or {})
    metadata[b"roast.schema_version"] = str(SCHEMA_VERSION).encode("ascii")
    metadata[b"roast.json_columns"] = json.dumps(
        sorted(json_field_set), separators=(",", ":")
    ).encode("utf-8")
    table = table.replace_schema_metadata(metadata)
    sink = pyarrow.BufferOutputStream()
    parquet.write_table(table, sink, compression="zstd")
    return sink.getvalue().to_pybytes()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    values: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            values.append(value)
    return tuple(values)


class FileSystemRunStore:
    """Persist standard run files and implement the resume/error sink protocols.

    Every update writes complete files through a temporary sibling and atomically
    replaces the previous version. A checkpoint is written last, so readers never
    resume from state newer than the materialized record files.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        parquet: bool = False,
    ) -> None:
        if type(parquet) is not bool:
            raise TypeError("parquet must be a boolean")
        self.root = _plain_root(root).expanduser().resolve()
        self.parquet_enabled = parquet
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_artifact_spec(cls, spec: ArtifactSpec) -> "FileSystemRunStore":
        if not isinstance(spec, ArtifactSpec):
            raise TypeError("spec must be an ArtifactSpec")
        parquet = spec.options.get("parquet", False)
        if type(parquet) is not bool:
            raise ValueError("ArtifactSpec.options.parquet must be a boolean")
        return cls(spec.output_uri, parquet=parquet)

    def run_directory(self, run_id: str) -> Path:
        return self.root / RUNS_DIRECTORY / _safe_run_id(run_id)

    def load(self, run_id: str) -> JSONObject | None:
        path = self.run_directory(run_id) / "checkpoint.json"
        if not path.exists():
            return None
        value = _read_json(path)
        if not isinstance(value, dict):
            raise ValueError("checkpoint.json must contain a JSON object")
        return cast(JSONObject, value)

    def save(self, run_id: str, state: ReadonlyJSONObject) -> None:
        plain_state = cast(JSONObject, to_plain_data(state))
        result = BenchmarkResult.from_dict(plain_state)
        if result.run_id != run_id:
            raise ValueError("Checkpoint run_id does not match the storage key")
        self.persist_result(result, checkpoint=plain_state)

    def persist_result(
        self,
        result: BenchmarkResult,
        *,
        checkpoint: Mapping[str, object] | None = None,
    ) -> Path:
        if not isinstance(result, BenchmarkResult):
            raise TypeError("result must be a BenchmarkResult")
        run_directory = self.run_directory(result.run_id)
        records_directory = run_directory / "records"
        expected = len(result.items) * len(result.config.models)
        errors = result.metadata.get("errors", ())
        error_rows = cast(list[dict[str, object]], to_plain_data(errors))
        if len(result.runs) < expected:
            state = "failed" if errors else "running"
        elif errors:
            state = "completed_with_errors"
        else:
            state = "completed"
        updated_at = _utc_now()
        streams: dict[str, list[dict[str, object]]] = {
            "items.jsonl": [item.to_dict() for item in result.items],
            "records/runs.jsonl": [record.to_dict() for record in result.runs],
            "records/predictions.jsonl": [
                record.to_dict() for record in result.predictions
            ],
            "records/metrics.jsonl": [record.to_dict() for record in result.metrics],
            "errors.jsonl": error_rows,
        }
        files: dict[str, bytes] = {
            "config.json": _json_bytes(result.config.to_dict()),
            **{
                relative_path: _jsonl_bytes(rows)
                for relative_path, rows in streams.items()
            },
            "run_metadata.json": _json_bytes(
                {
                    "schema_version": SCHEMA_VERSION,
                    "run_id": result.run_id,
                    "run_name": result.config.run.run_name,
                    "task_kind": result.task_kind,
                    "state": state,
                    "updated_at": updated_at,
                    "counts": {
                        "items": len(result.items),
                        "runs": len(result.runs),
                        "predictions": len(result.predictions),
                        "metrics": len(result.metrics),
                        "errors": len(errors),
                    },
                }
            ),
        }
        if self.parquet_enabled:
            for jsonl_path, rows in streams.items():
                fields, json_fields = _PARQUET_STREAMS[jsonl_path]
                parquet_path = str(Path(jsonl_path).with_suffix(".parquet")).replace(
                    "\\", "/"
                )
                files[parquet_path] = _parquet_bytes(
                    rows,
                    fields=fields,
                    json_fields=json_fields,
                )
        manifest_entries = []
        for relative_path, content in files.items():
            _atomic_write(run_directory / relative_path, content)
            manifest_entries.append(
                {
                    "path": relative_path.replace("\\", "/"),
                    "media_type": (
                        "application/x-ndjson"
                        if relative_path.endswith(".jsonl")
                        else PARQUET_MEDIA_TYPE
                        if relative_path.endswith(".parquet")
                        else "application/json"
                    ),
                    "sha256": sha256(content).hexdigest(),
                }
            )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_id": result.run_id,
            "files": sorted(manifest_entries, key=lambda value: value["path"]),
        }
        _atomic_write(run_directory / "manifest.json", _json_bytes(manifest))
        checkpoint_value = result.to_dict() if checkpoint is None else dict(checkpoint)
        _atomic_write(run_directory / "checkpoint.json", _json_bytes(checkpoint_value))
        self._update_registry(result, state=state, updated_at=updated_at)
        return run_directory

    def persist_errors(
        self,
        run_id: str,
        errors: tuple[ExecutionError, ...],
        spec: ArtifactSpec,
    ) -> ArtifactRecord:
        path = self.run_directory(run_id) / "errors.jsonl"
        error_rows = [error.to_dict() for error in errors]
        content = _jsonl_bytes(error_rows)
        parquet_content = None
        if self.parquet_enabled:
            fields, json_fields = _PARQUET_STREAMS["errors.jsonl"]
            parquet_content = _parquet_bytes(
                error_rows,
                fields=fields,
                json_fields=json_fields,
            )
        _atomic_write(path, content)
        if parquet_content is not None:
            _atomic_write(path.with_suffix(".parquet"), parquet_content)
        relative = path.relative_to(self.root).as_posix()
        return ArtifactRecord(
            artifact_id="execution-errors",
            kind="execution_errors",
            uri=relative,
            media_type="application/x-ndjson",
            checksum=f"sha256:{sha256(content).hexdigest()}",
            metadata={"record_count": len(errors)},
        )

    def list_runs(self) -> tuple[ReadonlyJSONObject, ...]:
        return cast(tuple[ReadonlyJSONObject, ...], _read_jsonl(self.root / REGISTRY_PATH))

    def _update_registry(self, result: BenchmarkResult, *, state: str, updated_at: str) -> None:
        path = self.root / REGISTRY_PATH
        entries = list(_read_jsonl(path))
        current = {
            "schema_version": SCHEMA_VERSION,
            "run_id": result.run_id,
            "run_name": result.config.run.run_name,
            "task_kind": result.task_kind,
            "state": state,
            "uri": f"{RUNS_DIRECTORY}/{result.run_id}/run_metadata.json",
            "updated_at": updated_at,
        }
        replaced = False
        for index, entry in enumerate(entries):
            if entry.get("run_id") == result.run_id:
                entries[index] = current
                replaced = True
                break
        if not replaced:
            entries.append(current)
        _atomic_write(path, _jsonl_bytes(entries))
        if self.parquet_enabled:
            _atomic_write(
                path.with_suffix(".parquet"),
                _parquet_bytes(entries, fields=_REGISTRY_PARQUET_FIELDS),
            )
