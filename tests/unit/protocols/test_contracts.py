from __future__ import annotations

from typing import get_type_hints

from examples.custom_plugins import (
    AbsoluteError,
    InlineNumbers,
    NumericPredictionTask,
    ScaleModel,
    build_registries,
)
from roast.protocols.dataset import DatasetProvider
from roast.protocols.hooks import ProgressHook, ResumeStore
from roast.protocols.metric import Metric
from roast.protocols.model import ModelAdapter
from roast.protocols.task import TaskAdapter


def test_example_plugins_satisfy_public_protocols_structurally() -> None:
    assert isinstance(InlineNumbers({}), DatasetProvider)
    assert isinstance(ScaleModel({}), ModelAdapter)
    assert isinstance(AbsoluteError({}), Metric)
    assert isinstance(NumericPredictionTask({}), TaskAdapter)


def test_custom_task_kind_and_adapters_register_without_framework_code() -> None:
    datasets, models, metrics, tasks = build_registries()

    assert datasets.names() == ("example.inline_numbers",)
    assert models.names() == ("example.scale",)
    assert metrics.names() == ("example.absolute_error",)
    assert tasks.names() == ("example.numeric_prediction",)


def test_all_public_protocol_annotations_are_runtime_resolvable() -> None:
    methods = (
        DatasetProvider.load,
        ModelAdapter.availability,
        Metric.compute,
        TaskAdapter.execute_item,
        ProgressHook.on_event,
        ResumeStore.load,
        ResumeStore.save,
    )

    for method in methods:
        assert get_type_hints(method)
