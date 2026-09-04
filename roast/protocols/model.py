from typing import Protocol, runtime_checkable

from roast.core.events import Availability


@runtime_checkable
class ModelAdapter(Protocol):
    """Expose availability shared by all task-specific model capabilities."""

    def availability(self) -> Availability: ...
