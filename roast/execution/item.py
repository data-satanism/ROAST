from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from roast.core.config import MetricSpec
from roast.core.records import (
    ItemRecord,
    MetricRecord,
    PredictionRecord,
    RunRecord,
)
from roast.core.schema import to_plain_data
from roast.core.status import RunStatus
from roast.execution.errors import (
    ExecutionError,
    ItemNotAvailable,
    SkipItem,
    _execution_error,
    record_id,
)
from roast.protocols.metric import Metric, MetricInput
from roast.protocols.model import ModelAdapter
from roast.protocols.task import ItemExecutionContext, PredictionOutput, TaskAdapter


Clock = Callable[[], datetime]
ResolvedMetric = tuple[MetricSpec, Metric]


@dataclass(frozen=True)
class ItemExecutionResult:
    """Collect records produced by one item and model execution."""

    run: RunRecord
    prediction: PredictionRecord | None = None
    metrics: tuple[MetricRecord, ...] = ()
    errors: tuple[ExecutionError, ...] = ()


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for lifecycle records."""

    return datetime.now(timezone.utc)


def _timestamp(clock: Clock) -> str:
    value = clock()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def status_result(
    *,
    run_id: str,
    item: ItemRecord,
    model_id: str,
    status: RunStatus,
    message: str,
    clock: Clock = utc_now,
) -> ItemExecutionResult:
    """Create a terminal lifecycle result without invoking a task adapter."""

    timestamp = _timestamp(clock)
    return ItemExecutionResult(
        run=RunRecord(
            record_id=record_id(
                "run", run_id, item.dataset_id, model_id, item.item_id
            ),
            run_id=run_id,
            dataset_id=item.dataset_id,
            model_id=model_id,
            item_id=item.item_id,
            status=status,
            message=message,
            started_at=timestamp,
            finished_at=timestamp,
        )
    )


def failed_status_result(
    error: Exception,
    *,
    run_id: str,
    stage: str,
    item: ItemRecord,
    model_id: str,
    include_traceback: bool,
    clock: Clock = utc_now,
) -> ItemExecutionResult:
    """Create a failed lifecycle result for a pre-execution model error."""

    result = status_result(
        run_id=run_id,
        item=item,
        model_id=model_id,
        status=RunStatus.FAILED,
        message=str(error) or type(error).__name__,
        clock=clock,
    )
    captured = _execution_error(
        error,
        run_id=run_id,
        stage=stage,
        item=item,
        model_id=model_id,
        metric_id=None,
        include_traceback=include_traceback,
    )
    return ItemExecutionResult(run=result.run, errors=(captured,))


def execute_item(
    *,
    run_id: str,
    task: TaskAdapter,
    item: ItemRecord,
    model: ModelAdapter,
    model_id: str,
    metrics: tuple[ResolvedMetric, ...],
    context: ItemExecutionContext,
    include_traceback: bool,
    clock: Clock = utc_now,
) -> ItemExecutionResult:
    """Execute one task item and translate its outcome into standard records."""

    started_at = _timestamp(clock)
    run_record_id = record_id(
        "run", run_id, item.dataset_id, model_id, item.item_id
    )
    try:
        output = task.execute_item(item, model, context)
        if not isinstance(output, PredictionOutput):
            raise TypeError("TaskAdapter.execute_item() must return PredictionOutput")
    except SkipItem as error:
        return ItemExecutionResult(
            run=RunRecord(
                record_id=run_record_id,
                run_id=run_id,
                dataset_id=item.dataset_id,
                model_id=model_id,
                item_id=item.item_id,
                status=RunStatus.SKIPPED,
                message=str(error),
                started_at=started_at,
                finished_at=_timestamp(clock),
            )
        )
    except ItemNotAvailable as error:
        return ItemExecutionResult(
            run=RunRecord(
                record_id=run_record_id,
                run_id=run_id,
                dataset_id=item.dataset_id,
                model_id=model_id,
                item_id=item.item_id,
                status=RunStatus.NOT_AVAILABLE,
                message=str(error),
                started_at=started_at,
                finished_at=_timestamp(clock),
            )
        )
    except Exception as error:
        captured = _execution_error(
            error,
            run_id=run_id,
            stage="task",
            item=item,
            model_id=model_id,
            metric_id=None,
            include_traceback=include_traceback,
        )
        return ItemExecutionResult(
            run=RunRecord(
                record_id=run_record_id,
                run_id=run_id,
                dataset_id=item.dataset_id,
                model_id=model_id,
                item_id=item.item_id,
                status=RunStatus.FAILED,
                message=captured.message,
                started_at=started_at,
                finished_at=_timestamp(clock),
            ),
            errors=(captured,),
        )

    prediction = PredictionRecord(
        record_id=record_id(
            "prediction", run_id, item.dataset_id, model_id, item.item_id
        ),
        run_id=run_id,
        dataset_id=item.dataset_id,
        model_id=model_id,
        item_id=item.item_id,
        prediction=output.prediction,
        truth=output.truth,
        metadata=output.metadata,
    )
    metric_records: list[MetricRecord] = []
    errors: list[ExecutionError] = []
    metric_context = {
        "task_kind": context.task_kind,
        "task_options": to_plain_data(context.options),
        "prediction_metadata": to_plain_data(output.metadata),
    }
    for metric_spec, metric in metrics:
        metric_record_id = record_id(
            "metric",
            run_id,
            item.dataset_id,
            model_id,
            item.item_id,
            metric_spec.metric_id,
        )
        try:
            value = metric.compute(
                MetricInput(
                    truth=output.truth,
                    prediction=output.prediction,
                    item=item,
                    spec=metric_spec,
                    context=metric_context,
                )
            )
            metric_records.append(
                MetricRecord(
                    record_id=metric_record_id,
                    run_id=run_id,
                    dataset_id=item.dataset_id,
                    model_id=model_id,
                    item_id=item.item_id,
                    metric_id=metric_spec.metric_id,
                    value=value,
                )
            )
        except Exception as error:
            captured = _execution_error(
                error,
                run_id=run_id,
                stage="metric",
                item=item,
                model_id=model_id,
                metric_id=metric_spec.metric_id,
                include_traceback=include_traceback,
            )
            errors.append(captured)
            metric_records.append(
                MetricRecord(
                    record_id=metric_record_id,
                    run_id=run_id,
                    dataset_id=item.dataset_id,
                    model_id=model_id,
                    item_id=item.item_id,
                    metric_id=metric_spec.metric_id,
                    value=None,
                    status=RunStatus.FAILED,
                    metadata={"error_id": captured.error_id},
                )
            )

    status = RunStatus.FAILED if errors else RunStatus.SUCCESS
    message = "metric evaluation failed" if errors else ""
    return ItemExecutionResult(
        run=RunRecord(
            record_id=run_record_id,
            run_id=run_id,
            dataset_id=item.dataset_id,
            model_id=model_id,
            item_id=item.item_id,
            status=status,
            message=message,
            started_at=started_at,
            finished_at=_timestamp(clock),
        ),
        prediction=prediction,
        metrics=tuple(metric_records),
        errors=tuple(errors),
    )
