from __future__ import annotations

import pytest

from examples.custom_plugins import NumericPredictionTask
from roast.plugins.errors import (
    DuplicatePluginError,
    RegistrationError,
    UnknownPluginError,
)
from roast.plugins.registry import (
    DatasetProviderRegistry,
    MetricDirection,
    MetricRegistry,
    ModelAdapterRegistry,
    Registry,
    TaskKindRegistry,
)


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

    with pytest.raises(DuplicatePluginError, match="already registered") as error:
        registry.register("example.one", lambda options: object())

    assert isinstance(error.value, ValueError)
    assert not isinstance(error.value, LookupError)


def test_registry_reports_unknown_names_and_available_plugins() -> None:
    registry: Registry[object] = Registry("example plugin")
    registry.register("example.available", lambda options: object())

    with pytest.raises(UnknownPluginError, match="example.available") as error:
        registry.get("missing")

    assert isinstance(error.value, LookupError)


def test_registry_rejects_invalid_names_and_factories() -> None:
    registry: Registry[object] = Registry("example plugin")
    with pytest.raises(RegistrationError, match="non-empty"):
        registry.register("", lambda options: object())
    with pytest.raises(RegistrationError, match="callable"):
        registry.register("broken", object())  # type: ignore[arg-type]


def test_task_kind_registry_uses_arbitrary_string_names() -> None:
    registry = TaskKindRegistry()
    registry.register("external.numeric_prediction", NumericPredictionTask)

    task = registry.create("external.numeric_prediction", {})

    assert isinstance(task, NumericPredictionTask)


def test_dataset_provider_registry_has_a_specific_public_kind() -> None:
    registry = DatasetProviderRegistry()
    registry.register("external.memory", lambda options: object())  # type: ignore[arg-type]

    with pytest.raises(
        UnknownPluginError,
        match=r"registered dataset provider names: external\.memory",
    ):
        registry.get("missing")


def test_model_adapter_registry_has_a_specific_public_kind() -> None:
    registry = ModelAdapterRegistry()
    registry.register("external.lazy_model", lambda options: object())  # type: ignore[arg-type]

    with pytest.raises(
        UnknownPluginError,
        match=r"registered model adapter names: external\.lazy_model",
    ):
        registry.get("missing")


def test_metric_registry_exposes_direction_compatibility_and_aliases() -> None:
    registry = MetricRegistry()
    factory = lambda options: object()  # type: ignore[return-value]
    registry.register(
        "external.loss",
        factory,
        direction=MetricDirection.MINIMIZE,
        task_kinds=("regression",),
        aliases=("external.loss@1",),
    )

    assert registry.get("external.loss@1") is factory
    assert registry.metadata("external.loss@1").direction is MetricDirection.MINIMIZE
    registry.validate_task("external.loss", "regression")
    with pytest.raises(RegistrationError, match="not compatible"):
        registry.validate_task("external.loss", "classification")
