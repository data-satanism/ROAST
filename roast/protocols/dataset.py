from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from ..core.config import DatasetSpec
from ..core.records import ItemRecord


@runtime_checkable
class DatasetProvider(Protocol):
    """Provide task-neutral items for a declarative dataset specification."""

    def load(self, spec: DatasetSpec) -> Iterable[ItemRecord]: ...
