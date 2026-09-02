from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar, cast

from ..core.schema import ReadonlyJSONObject, freeze_json_value
from ..protocols.task import TaskAdapter
from .errors import DuplicatePluginError, RegistryError, UnknownPluginError


T = TypeVar("T")
PluginFactory = Callable[[ReadonlyJSONObject], T]


class Registry(Generic[T]):
    """Map stable plugin names to typed factories.

    Args:
        kind: Human-readable plugin kind used in error messages.
    """

    def __init__(self, kind: str = "plugin") -> None:
        if not isinstance(kind, str) or not kind.strip():
            raise RegistryError("Registry kind must be a non-empty string")
        self._kind = kind
        self._factories: dict[str, PluginFactory[T]] = {}

    def register(self, name: str, factory: PluginFactory[T]) -> None:
        if not isinstance(name, str) or not name.strip():
            raise RegistryError(f"{self._kind} name must be a non-empty string")
        if not callable(factory):
            raise RegistryError(f"Factory for {self._kind} {name!r} must be callable")
        if name in self._factories:
            raise DuplicatePluginError(f"{self._kind} {name!r} is already registered")
        self._factories[name] = factory

    def get(self, name: str) -> PluginFactory[T]:
        try:
            return self._factories[name]
        except KeyError as error:
            available = ", ".join(self.names()) or "none"
            raise UnknownPluginError(
                f"Unknown {self._kind} {name!r}; registered {self._kind} names: {available}"
            ) from error

    def create(self, name: str, options: ReadonlyJSONObject) -> T:
        frozen = cast(ReadonlyJSONObject, freeze_json_value(dict(options)))
        return self.get(name)(frozen)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


class TaskKindRegistry(Registry[TaskAdapter]):
    """Map task-kind names to task adapter factories."""

    def __init__(self) -> None:
        super().__init__("task kind")
