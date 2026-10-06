from __future__ import annotations

import hashlib
import traceback as traceback_module
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from roast.core.schema import (
    SCHEMA_VERSION,
    SchemaError,
    SchemaMixin,
    ensure_schema_version,
    optional_string,
    require_schema_version,
    require_string,
)

if TYPE_CHECKING:
    from roast.core.records import BenchmarkResult, ItemRecord


def record_id(kind: str, run_id: str, *parts: str) -> str:
    """Build a stable, compact record identifier from execution coordinates."""

    source = "\x1f".join((run_id, kind, *parts)).encode("utf-8")
    digest = hashlib.sha256(source).hexdigest()[:20]
    return f"{kind}-{digest}"


def _exception_name(error: Exception) -> str:
    error_type = type(error)
    return f"{error_type.__module__}.{error_type.__qualname__}"


class SkipItem(RuntimeError):
    """Request a task-neutral skipped status for the current item."""


class ItemNotAvailable(RuntimeError):
    """Report that the current item cannot run in the present environment."""


@dataclass(frozen=True)
class ExecutionError(SchemaMixin):
    """Describe one error captured while executing a suite.

    Attributes:
        error_id: Identifier unique within the benchmark result.
        run_id: Identifier of the containing benchmark run.
        stage: Lifecycle stage that raised the error.
        exception_type: Qualified exception class name.
        message: Human-readable exception message.
        dataset_id: Associated dataset identifier, when available.
        model_id: Associated model identifier, when available.
        item_id: Associated item identifier, when available.
        metric_id: Associated metric identifier, when available.
        traceback: Optional formatted traceback controlled by execution policy.
        schema_version: Version of the serialized schema.
    """

    error_id: str
    run_id: str
    stage: str
    exception_type: str
    message: str
    dataset_id: str | None = None
    model_id: str | None = None
    item_id: str | None = None
    metric_id: str | None = None
    traceback: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ensure_schema_version(self.schema_version, schema_name="ExecutionError")
        for field_name in (
            "error_id",
            "run_id",
            "stage",
            "exception_type",
            "message",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise SchemaError(
                    f"ExecutionError.{field_name} must be a non-empty string"
                )
        for field_name in (
            "dataset_id",
            "model_id",
            "item_id",
            "metric_id",
            "traceback",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise SchemaError(
                    f"ExecutionError.{field_name} must be a string or null"
                )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionError":
        return cls(
            error_id=require_string(data, "error_id", schema_name="ExecutionError"),
            run_id=require_string(data, "run_id", schema_name="ExecutionError"),
            stage=require_string(data, "stage", schema_name="ExecutionError"),
            exception_type=require_string(
                data, "exception_type", schema_name="ExecutionError"
            ),
            message=require_string(data, "message", schema_name="ExecutionError"),
            dataset_id=optional_string(
                data, "dataset_id", schema_name="ExecutionError"
            ),
            model_id=optional_string(data, "model_id", schema_name="ExecutionError"),
            item_id=optional_string(data, "item_id", schema_name="ExecutionError"),
            metric_id=optional_string(data, "metric_id", schema_name="ExecutionError"),
            traceback=optional_string(data, "traceback", schema_name="ExecutionError"),
            schema_version=require_schema_version(data, schema_name="ExecutionError"),
        )


def _execution_error(
    error: Exception,
    *,
    run_id: str,
    stage: str,
    item: ItemRecord,
    model_id: str,
    metric_id: str | None,
    include_traceback: bool,
) -> ExecutionError:
    """Convert an exception raised for one item into a serializable record."""

    message = str(error) or type(error).__name__
    parts = [item.dataset_id, model_id, item.item_id]
    if metric_id is not None:
        parts.append(metric_id)
    return ExecutionError(
        error_id=record_id("error", run_id, stage, *parts),
        run_id=run_id,
        stage=stage,
        exception_type=_exception_name(error),
        message=message,
        dataset_id=item.dataset_id,
        model_id=model_id,
        item_id=item.item_id,
        metric_id=metric_id,
        traceback=(
            "".join(
                traceback_module.format_exception(
                    type(error), error, error.__traceback__
                )
            )
            if include_traceback
            else None
        ),
    )


def _suite_execution_error(
    error: Exception,
    *,
    run_id: str,
    stage: str,
    include_traceback: bool,
    dataset_id: str | None = None,
    metric_id: str | None = None,
) -> ExecutionError:
    """Capture a plugin setup failure without inventing an item or run record."""

    return ExecutionError(
        error_id=record_id("error", run_id, stage, dataset_id or "", metric_id or ""),
        run_id=run_id,
        stage=stage,
        exception_type=_exception_name(error),
        message=str(error) or type(error).__name__,
        dataset_id=dataset_id,
        metric_id=metric_id,
        traceback=(
            "".join(traceback_module.format_exception(type(error), error, error.__traceback__))
            if include_traceback
            else None
        ),
    )


class SuiteExecutionError(RuntimeError):
    """Expose the partial result produced by suite or fail-fast execution."""

    def __init__(self, message: str, partial_result: "BenchmarkResult") -> None:
        super().__init__(message)
        self.partial_result = partial_result
