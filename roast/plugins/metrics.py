from __future__ import annotations

from math import sqrt

from roast.core.schema import JSONValue, ReadonlyJSONObject
from roast.plugins.registry import MetricDirection, MetricRegistry
from roast.protocols.metric import MetricInput


def _pairs(truth: JSONValue, prediction: JSONValue) -> tuple[tuple[float, float], ...]:
    if isinstance(truth, (list, tuple)) and isinstance(prediction, (list, tuple)):
        if len(truth) != len(prediction):
            raise ValueError("truth and prediction must have the same length")
        pairs: list[tuple[float, float]] = []
        for expected, actual in zip(truth, prediction):
            pairs.extend(_pairs(expected, actual))
        if not pairs:
            raise ValueError("truth and prediction must not be empty")
        return tuple(pairs)
    if isinstance(truth, bool) or isinstance(prediction, bool):
        raise TypeError("numeric metrics do not accept boolean values")
    if not isinstance(truth, (int, float)) or not isinstance(prediction, (int, float)):
        raise TypeError("numeric metrics require numbers or equally-shaped arrays")
    return ((float(truth), float(prediction)),)


class Accuracy:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def compute(self, value: MetricInput) -> float:
        truth = value.truth if isinstance(value.truth, (list, tuple)) else (value.truth,)
        prediction = (
            value.prediction
            if isinstance(value.prediction, (list, tuple))
            else (value.prediction,)
        )
        if len(truth) != len(prediction) or not truth:
            raise ValueError("truth and prediction must be non-empty and equally sized")
        return sum(expected == actual for expected, actual in zip(truth, prediction)) / len(truth)


class MeanAbsoluteError:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def compute(self, value: MetricInput) -> float:
        pairs = _pairs(value.truth, value.prediction)
        return sum(abs(expected - actual) for expected, actual in pairs) / len(pairs)


class RootMeanSquaredError:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def compute(self, value: MetricInput) -> float:
        pairs = _pairs(value.truth, value.prediction)
        return sqrt(sum((expected - actual) ** 2 for expected, actual in pairs) / len(pairs))


class SymmetricMeanAbsolutePercentageError:
    def __init__(self, options: ReadonlyJSONObject) -> None:
        pass

    def compute(self, value: MetricInput) -> float:
        pairs = _pairs(value.truth, value.prediction)
        terms = [
            0.0
            if expected == actual == 0
            else 2 * abs(actual - expected) / (abs(expected) + abs(actual))
            for expected, actual in pairs
        ]
        return sum(terms) / len(terms)


def standard_metric_registry() -> MetricRegistry:
    """Return a new registry containing dependency-free reference metrics."""

    registry = MetricRegistry()
    registry.register(
        "accuracy",
        Accuracy,
        direction=MetricDirection.MAXIMIZE,
        task_kinds=("classification",),
        aliases=("accuracy@1",),
    )
    registry.register(
        "mae",
        MeanAbsoluteError,
        direction=MetricDirection.MINIMIZE,
        task_kinds=("forecasting", "regression"),
        aliases=("mae@1",),
    )
    registry.register(
        "rmse",
        RootMeanSquaredError,
        direction=MetricDirection.MINIMIZE,
        task_kinds=("forecasting", "regression"),
        aliases=("rmse@1",),
    )
    registry.register(
        "smape",
        SymmetricMeanAbsolutePercentageError,
        direction=MetricDirection.MINIMIZE,
        task_kinds=("forecasting",),
        aliases=("smape@1",),
    )
    return registry
