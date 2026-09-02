from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..core.config import MetricSpec
from ..core.records import ItemRecord
from ..core.schema import (
    JSONValue,
    ReadonlyJSONObject,
    ensure_json_value,
    freeze_json_value,
)


@dataclass(frozen=True)
class MetricInput:
    """Collect explicit inputs required by a metric implementation.

    Attributes:
        truth: Task-specific expected value.
        prediction: Task-specific predicted value.
        item: Source benchmark item.
        spec: Declarative metric specification.
        context: Read-only task-specific JSON context.
    """

    truth: JSONValue
    prediction: JSONValue
    item: ItemRecord
    spec: MetricSpec
    context: ReadonlyJSONObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        ensure_json_value(self.truth, path="MetricInput.truth")
        ensure_json_value(self.prediction, path="MetricInput.prediction")
        if not isinstance(self.item, ItemRecord):
            raise TypeError("MetricInput.item must be an ItemRecord")
        if not isinstance(self.spec, MetricSpec):
            raise TypeError("MetricInput.spec must be a MetricSpec")
        object.__setattr__(self, "context", freeze_json_value(dict(self.context)))


@runtime_checkable
class Metric(Protocol):
    """Compute one scalar value from an explicit metric input envelope."""

    def compute(self, value: MetricInput) -> float: ...
