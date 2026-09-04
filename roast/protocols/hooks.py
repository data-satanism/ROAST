from typing import Protocol, runtime_checkable

from roast.core.events import ProgressEvent
from roast.core.schema import (
    JSONObject,
    ReadonlyJSONObject,
)


@runtime_checkable
class ProgressHook(Protocol):
    """Consume optional versioned lifecycle events."""

    def on_event(self, event: ProgressEvent) -> None: ...


@runtime_checkable
class ResumeStore(Protocol):
    """Load and save optional task-neutral JSON resume state."""

    def load(self, run_id: str) -> JSONObject | None: ...

    def save(self, run_id: str, state: ReadonlyJSONObject) -> None: ...
