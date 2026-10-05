from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar, cast

from roast.core.schema import ReadonlyJSONObject, freeze_json_value
from roast.plugins.errors import (
    DuplicatePluginError,
    RegistrationError,
    UnknownPluginError,
)
from roast.protocols.task import TaskAdapter
from roast.protocols.dataset import DatasetProvider
from roast.protocols.model import ModelAdapter
from roast.protocols.metric import Metric


T = TypeVar("T")
PluginFactory = Callable[[ReadonlyJSONObject], T]


class Registry(Generic[T]):
    """Map stable plugin names to typed factories.

    Args:
        kind: Human-readable plugin kind used in error messages.
    """

    def __init__(self, kind: str = "plugin") -> None:
        if not isinstance(kind, str) or not kind.strip():
            raise RegistrationError("Registry kind must be a non-empty string")
        self._kind = kind
        self._factories: dict[str, PluginFactory[T]] = {}

    def register(self, name: str, factory: PluginFactory[T]) -> None:
        if not isinstance(name, str) or not name.strip():
            raise RegistrationError(f"{self._kind} name must be a non-empty string")
        if not callable(factory):
            raise RegistrationError(
                f"Factory for {self._kind} {name!r} must be callable"
            )
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


class DatasetProviderRegistry(Registry[DatasetProvider]):
    """Map dataset provider names to factories.

    Dataset options remain opaque to ROAST and are passed to the provider factory
    as an immutable JSON mapping.  The returned provider receives the complete
    :class:`~roast.core.config.DatasetSpec` when the suite is executed.
    """

    def __init__(self) -> None:
        super().__init__("dataset provider")


class ModelAdapterRegistry(Registry[ModelAdapter]):
    """Map task-agnostic model adapter names to lazy factories."""

    def __init__(self) -> None:
        super().__init__("model adapter")


class MetricDirection(str, Enum):
    """Describe which direction represents a better metric value."""

    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


@dataclass(frozen=True)
class MetricMetadata:
    """Stable ranking and compatibility metadata for a registered metric."""

    name: str
    direction: MetricDirection
    task_kinds: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


class MetricRegistry(Registry[Metric]):
    """Register metrics with ranking and task compatibility metadata."""

    def __init__(self) -> None:
        super().__init__("metric")
        self._metadata: dict[str, MetricMetadata] = {}
        self._aliases: dict[str, str] = {}

    def register(
        self,
        name: str,
        factory: PluginFactory[Metric],
        *,
        direction: MetricDirection | str = MetricDirection.MAXIMIZE,
        task_kinds: tuple[str, ...] = (),
        aliases: tuple[str, ...] = (),
    ) -> None:
        try:
            normalized_direction = MetricDirection(direction)
        except ValueError as error:
            raise RegistrationError(
                "Metric direction must be 'minimize' or 'maximize'"
            ) from error
        normalized_tasks = tuple(task_kinds)
        normalized_aliases = tuple(aliases)
        for label, values in (("task kind", normalized_tasks), ("alias", normalized_aliases)):
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise RegistrationError(f"Metric {label} values must be non-empty strings")
            if len(values) != len(set(values)):
                raise RegistrationError(f"Metric {label} values must be unique")
        occupied = set(self._factories) | set(self._aliases)
        if name in self._aliases:
            raise DuplicatePluginError(f"metric {name!r} is already registered as an alias")
        conflicts = occupied.intersection(normalized_aliases)
        if conflicts or name in normalized_aliases:
            conflict = sorted(conflicts or {name})[0]
            raise DuplicatePluginError(f"metric name or alias {conflict!r} is already registered")
        super().register(name, factory)
        self._metadata[name] = MetricMetadata(
            name=name,
            direction=normalized_direction,
            task_kinds=tuple(sorted(normalized_tasks)),
            aliases=tuple(sorted(normalized_aliases)),
        )
        self._aliases.update({alias: name for alias in normalized_aliases})

    def canonical_name(self, name: str) -> str:
        return self._aliases.get(name, name)

    def get(self, name: str) -> PluginFactory[Metric]:
        return super().get(self.canonical_name(name))

    def metadata(self, name: str) -> MetricMetadata:
        canonical = self.canonical_name(name)
        self.get(canonical)
        return self._metadata[canonical]

    def validate_task(self, name: str, task_kind: str) -> None:
        metadata = self.metadata(name)
        if metadata.task_kinds and task_kind not in metadata.task_kinds:
            supported = ", ".join(metadata.task_kinds)
            raise RegistrationError(
                f"Metric {name!r} is not compatible with task kind {task_kind!r}; "
                f"compatible task kinds: {supported}"
            )
