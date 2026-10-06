import math

from hypothesis import given, strategies as st
import pytest

from roast.core.config import MetricSpec, PluginSpec
from roast.core.records import ItemRecord
from roast.core.schema import SchemaError
from roast.plugins.metrics import standard_metric_registry
from roast.plugins.registry import MetricDirection
from roast.protocols.metric import MetricInput


FINITE_NUMBERS = st.floats(
    min_value=-1_000_000,
    max_value=1_000_000,
    allow_nan=False,
    allow_infinity=False,
)
NUMERIC_VECTORS = st.lists(FINITE_NUMBERS, min_size=1, max_size=20)


@st.composite
def equal_length_vector_pairs(draw):
    size = draw(st.integers(min_value=1, max_value=20))
    vectors = st.lists(FINITE_NUMBERS, min_size=size, max_size=size)
    return draw(vectors), draw(vectors)


@st.composite
def mismatched_vector_pairs(draw):
    first_size, second_size = draw(
        st.tuples(
            st.integers(min_value=1, max_value=20),
            st.integers(min_value=1, max_value=20),
        ).filter(lambda sizes: sizes[0] != sizes[1])
    )
    return (
        draw(st.lists(FINITE_NUMBERS, min_size=first_size, max_size=first_size)),
        draw(st.lists(FINITE_NUMBERS, min_size=second_size, max_size=second_size)),
    )


def metric_input(truth, prediction, name: str) -> MetricInput:
    return MetricInput(
        truth=truth,
        prediction=prediction,
        item=ItemRecord("item", "dataset", payload=None),
        spec=MetricSpec(name, PluginSpec(name)),
    )


def test_standard_metrics_compute_without_external_dependencies() -> None:
    registry = standard_metric_registry()

    accuracy = registry.create("accuracy@1", {})
    mae = registry.create("mae", {})
    rmse = registry.create("rmse", {})
    smape = registry.create("smape", {})

    assert accuracy.compute(metric_input([1, 0, 1], [1, 1, 1], "accuracy")) == 2 / 3
    assert mae.compute(metric_input([1, 3], [2, 5], "mae")) == 1.5
    assert rmse.compute(metric_input([1, 3], [2, 5], "rmse")) == (2.5 ** 0.5)
    assert smape.compute(metric_input([0, 2], [0, 1], "smape")) == 1 / 3
    assert registry.metadata("accuracy").direction is MetricDirection.MAXIMIZE
    assert registry.metadata("mae").direction is MetricDirection.MINIMIZE


@given(equal_length_vector_pairs())
def test_standard_metrics_are_invariant_to_common_reordering(
    vectors: tuple[list[float], list[float]],
) -> None:
    truth, prediction = vectors
    registry = standard_metric_registry()

    for name in ("accuracy", "mae", "rmse", "smape"):
        metric = registry.create(name, {})
        original = metric.compute(metric_input(truth, prediction, name))
        reordered = metric.compute(
            metric_input(list(reversed(truth)), list(reversed(prediction)), name)
        )
        assert reordered == pytest.approx(original)


@given(equal_length_vector_pairs())
def test_standard_metrics_preserve_values_for_equivalent_singleton_shapes(
    vectors: tuple[list[float], list[float]],
) -> None:
    truth, prediction = vectors
    registry = standard_metric_registry()
    nested_truth = [[value] for value in truth]
    nested_prediction = [[value] for value in prediction]

    for name in ("accuracy", "mae", "rmse", "smape"):
        metric = registry.create(name, {})
        flat = metric.compute(metric_input(truth, prediction, name))
        nested = metric.compute(metric_input(nested_truth, nested_prediction, name))
        assert nested == pytest.approx(flat)


@given(NUMERIC_VECTORS)
def test_standard_metrics_have_identity_values(values: list[float]) -> None:
    registry = standard_metric_registry()

    assert registry.create("accuracy", {}).compute(
        metric_input(values, values, "accuracy")
    ) == 1.0
    for name in ("mae", "rmse", "smape"):
        assert registry.create(name, {}).compute(
            metric_input(values, values, name)
        ) == pytest.approx(0.0)


@given(mismatched_vector_pairs())
def test_standard_metrics_reject_mismatched_outer_shapes(
    vectors: tuple[list[float], list[float]],
) -> None:
    truth, prediction = vectors
    registry = standard_metric_registry()

    for name in ("accuracy", "mae", "rmse", "smape"):
        with pytest.raises(ValueError, match="same length|equally sized"):
            registry.create(name, {}).compute(metric_input(truth, prediction, name))


@given(
    NUMERIC_VECTORS,
    st.sampled_from((float("nan"), float("inf"), float("-inf"))),
    st.booleans(),
)
def test_metric_input_rejects_non_finite_values_at_any_position(
    values: list[float],
    non_finite: float,
    use_prediction: bool,
) -> None:
    position = len(values) // 2
    invalid = list(values)
    invalid[position] = non_finite
    truth = values if use_prediction else invalid
    prediction = invalid if use_prediction else values

    with pytest.raises(SchemaError, match="finite"):
        metric_input(truth, prediction, "mae")


@given(NUMERIC_VECTORS)
def test_standard_numeric_metrics_return_finite_values(values: list[float]) -> None:
    registry = standard_metric_registry()
    prediction = list(reversed(values))

    for name in ("mae", "rmse", "smape"):
        result = registry.create(name, {}).compute(
            metric_input(values, prediction, name)
        )
        assert math.isfinite(result)
