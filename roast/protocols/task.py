from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..core.records import ItemRecord
from ..core.schema import (
    JSONValue,
    ReadonlyJSONObject,
    ensure_json_value,
    freeze_json_value,
)
from .model import ModelAdapter


@dataclass(frozen=True)
class ItemExecutionContext:
    """Provide task-neutral context for one item execution.

    Attributes:
        task_kind: Registered name of the selected task adapter.
        options: Read-only JSON options owned by the task adapter.
    """

    task_kind: str
    options: ReadonlyJSONObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.task_kind, str) or not self.task_kind.strip():
            raise ValueError("ItemExecutionContext.task_kind must be a non-empty string")
        object.__setattr__(self, "options", freeze_json_value(dict(self.options)))


@dataclass(frozen=True)
class PredictionOutput:
    """Represent task-specific output before standard records are assembled.

    Attributes:
        prediction: Task-specific predicted value.
        truth: Task-specific expected value, when available.
        metadata: Read-only consumer-defined JSON metadata.
    """

    prediction: JSONValue
    truth: JSONValue = None
    metadata: ReadonlyJSONObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        ensure_json_value(self.prediction, path="PredictionOutput.prediction")
        ensure_json_value(self.truth, path="PredictionOutput.truth")
        object.__setattr__(self, "metadata", freeze_json_value(dict(self.metadata)))


@runtime_checkable
class TaskAdapter(Protocol):
    """Define one item's task semantics without owning the suite lifecycle."""

    def execute_item(
        self,
        item: ItemRecord,
        model: ModelAdapter,
        context: ItemExecutionContext,
    ) -> PredictionOutput: ...
