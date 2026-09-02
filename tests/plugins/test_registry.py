from __future__ import annotations

import pytest

from examples.custom_plugins import NumericPredictionTask
from roast.plugins.errors import (
    DuplicatePluginError,
    RegistryError,
    UnknownPluginError,
)
from roast.plugins.registry import Registry, TaskKindRegistry


def test_generic_registry_registers_and_creates_plugins() -> None:
    registry: Registry[object] = Registry("example plugin")
    registry.register("example.one", lambda options: {"options": options})

    created = registry.create("example.one", {"enabled": True})

    assert created == {"options": {"enabled": True}}
    with pytest.raises(TypeError):
        created["options"]["changed"] = True  # type: ignore[index]
    assert registry.names() == ("example.one",)


def test_registry_rejects_duplicate_names() -> None:
    registry: Registry[object] = Registry("example plugin")
    registry.register("example.one", lambda options: object())

    with pytest.raises(DuplicatePluginError, match="already registered"):
        registry.register("example.one", lambda options: object())


def test_registry_reports_unknown_names_and_available_plugins() -> None:
    registry: Registry[object] = Registry("example plugin")
    registry.register("example.available", lambda options: object())

    with pytest.raises(UnknownPluginError, match="example.available"):
        registry.get("missing")


def test_registry_rejects_invalid_names_and_factories() -> None:
    registry: Registry[object] = Registry("example plugin")
    with pytest.raises(RegistryError, match="non-empty"):
        registry.register("", lambda options: object())
    with pytest.raises(RegistryError, match="callable"):
        registry.register("broken", object())  # type: ignore[arg-type]


def test_task_kind_registry_uses_arbitrary_string_names() -> None:
    registry = TaskKindRegistry()
    registry.register("external.numeric_prediction", NumericPredictionTask)

    task = registry.create("external.numeric_prediction", {})

    assert isinstance(task, NumericPredictionTask)
