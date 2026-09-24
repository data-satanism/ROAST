from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn, cast
from uuid import uuid4

from roast.core.config import BenchmarkSuiteConfig
from roast.core.events import Availability, ProgressEvent
from roast.core.records import (
    ArtifactManifest,
    ArtifactRecord,
    BenchmarkResult,
    ItemRecord,
    MetricRecord,
    PredictionRecord,
    RunRecord,
)
from roast.core.schema import ReadonlyJSONObject, freeze_json_value
from roast.core.status import RunStatus
from roast.execution.artifacts import ErrorArtifactSink
from roast.execution.errors import (
    ExecutionError,
    SuiteExecutionError,
    _suite_execution_error,
)
from roast.execution.item import (
    Clock,
    ItemExecutionResult,
    ResolvedMetric,
    execute_item,
    failed_status_result,
    status_result,
    utc_now,
)
from roast.execution.policy import ExecutionPolicy
from roast.plugins.registry import Registry, TaskKindRegistry
from roast.plugins.errors import UnknownPluginError
from roast.protocols.dataset import DatasetProvider
from roast.protocols.hooks import ProgressHook, ResumeStore
from roast.protocols.metric import Metric
from roast.protocols.model import ModelAdapter
from roast.protocols.task import ItemExecutionContext, TaskAdapter


@dataclass(frozen=True)
class PluginRegistries:
    """Group the four registries required by suite execution.

    Attributes:
        datasets: Registered dataset provider factories.
        models: Registered model adapter factories.
        metrics: Registered metric factories.
        tasks: Registered task adapter factories.
    """

    datasets: Registry[DatasetProvider]
    models: Registry[ModelAdapter]
    metrics: Registry[Metric]
    tasks: TaskKindRegistry

    def __post_init__(self) -> None:
        for field_name in ("datasets", "models", "metrics", "tasks"):
            if not isinstance(getattr(self, field_name), Registry):
                raise TypeError(f"PluginRegistries.{field_name} must be a Registry")


def _new_run_id(config: BenchmarkSuiteConfig) -> str:
    return config.run.resume_run_id or f"{config.run.run_name}-{uuid4().hex}"


def _run_key(record: RunRecord) -> tuple[str, str, str]:
    return record.dataset_id, record.model_id, record.item_id


def _record_key(
    record: RunRecord | PredictionRecord | MetricRecord,
) -> tuple[str, str, str]:
    return record.dataset_id, record.model_id, record.item_id


def _configs_are_resume_compatible(
    previous: BenchmarkSuiteConfig,
    current: BenchmarkSuiteConfig,
) -> bool:
    return (
        previous.task_kind == current.task_kind
        and previous.task_options == current.task_options
        and previous.datasets == current.datasets
        and previous.models == current.models
        and previous.metrics == current.metrics
        and previous.run.run_name == current.run.run_name
        and previous.run.random_seed == current.run.random_seed
        and previous.run.primary_metric == current.run.primary_metric
        and previous.run.options == current.run.options
    )


def _errors_from_result(result: BenchmarkResult) -> list[ExecutionError]:
    raw_errors = result.metadata.get("errors", ())
    if not isinstance(raw_errors, (list, tuple)):
        raise ValueError("BenchmarkResult.metadata.errors must be an array")
    errors: list[ExecutionError] = []
    for raw_error in raw_errors:
        if not isinstance(raw_error, Mapping):
            raise ValueError("BenchmarkResult.metadata.errors must contain objects")
        errors.append(ExecutionError.from_dict(raw_error))
    return errors


class _PluginSetupFailure(Exception):
    """Carry the original plugin error and any items loaded before it failed."""

    def __init__(
        self,
        error: Exception,
        stage: str,
        *,
        items: tuple[ItemRecord, ...] = (),
        dataset_id: str | None = None,
        metric_id: str | None = None,
    ) -> None:
        super().__init__(str(error))
        self.error = error
        self.stage = stage
        self.items = items
        self.dataset_id = dataset_id
        self.metric_id = metric_id


class SuiteOrchestrator:
    """Run a task-neutral benchmark suite through registered plugins.

    Args:
        registries: Dataset, model, metric, and task registries.
        policy: Failure, traceback, artifact, and resume retry policy.
        progress_hook: Optional consumer of structured lifecycle events.
        resume_store: Optional storage used for incremental checkpoints.
        error_artifact_sink: Optional persistence hook for aggregated errors.
        clock: Timestamp provider, primarily useful for deterministic tests.
    """

    def __init__(
        self,
        registries: PluginRegistries,
        *,
        policy: ExecutionPolicy | None = None,
        progress_hook: ProgressHook | None = None,
        resume_store: ResumeStore | None = None,
        error_artifact_sink: ErrorArtifactSink | None = None,
        clock: Clock = utc_now,
    ) -> None:
        if not isinstance(registries, PluginRegistries):
            raise TypeError("registries must be PluginRegistries")
        if policy is not None and not isinstance(policy, ExecutionPolicy):
            raise TypeError("policy must be an ExecutionPolicy")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._registries = registries
        self._policy = policy if policy is not None else ExecutionPolicy()
        self._progress_hook = progress_hook
        self._resume_store = resume_store
        self._error_artifact_sink = error_artifact_sink
        self._clock = clock

    def _emit(
        self,
        kind: str,
        *,
        current: int,
        total: int,
        message: str = "",
        metadata: ReadonlyJSONObject | None = None,
    ) -> None:
        if self._progress_hook is None:
            return
        self._progress_hook.on_event(
            ProgressEvent(
                kind=kind,
                current=current,
                total=total,
                message=message,
                metadata=dict(metadata or {}),
            )
        )

    def _validate_plugin_names(self, config: BenchmarkSuiteConfig) -> None:
        """Reject unknown names before invoking any consumer plugin."""

        for spec in config.datasets:
            self._registries.datasets.get(spec.provider.name)
        for spec in config.models:
            self._registries.models.get(spec.adapter.name)
        for spec in config.metrics:
            self._registries.metrics.get(spec.metric.name)
        self._registries.tasks.get(config.task_kind)

    def _load_items(self, config: BenchmarkSuiteConfig) -> tuple[ItemRecord, ...]:
        items: list[ItemRecord] = []
        keys: set[tuple[str, str]] = set()
        for dataset_spec in config.datasets:
            try:
                provider = self._registries.datasets.create(
                    dataset_spec.provider.name,
                    dataset_spec.provider.options,
                )
            except UnknownPluginError:
                raise
            except Exception as error:
                raise _PluginSetupFailure(
                    error, "dataset_factory", items=tuple(items),
                    dataset_id=dataset_spec.dataset_id,
                ) from error
            try:
                iterator = iter(provider.load(dataset_spec))
            except Exception as error:
                raise _PluginSetupFailure(
                    error, "dataset_load", items=tuple(items),
                    dataset_id=dataset_spec.dataset_id,
                ) from error
            while True:
                try:
                    item = next(iterator)
                except StopIteration:
                    break
                except Exception as error:
                    raise _PluginSetupFailure(
                        error, "dataset_load", items=tuple(items),
                        dataset_id=dataset_spec.dataset_id,
                    ) from error
                if not isinstance(item, ItemRecord):
                    raise TypeError(
                        f"Dataset provider {dataset_spec.provider.name!r} returned "
                        f"{type(item).__name__}; expected ItemRecord"
                    )
                if item.dataset_id != dataset_spec.dataset_id:
                    raise ValueError(
                        f"Dataset provider {dataset_spec.provider.name!r} returned "
                        f"item {item.item_id!r} with dataset_id {item.dataset_id!r}; "
                        f"expected {dataset_spec.dataset_id!r}"
                    )
                key = (item.dataset_id, item.item_id)
                if key in keys:
                    raise ValueError(
                        f"Dataset providers returned duplicate item {key!r}"
                    )
                keys.add(key)
                items.append(item)
        return tuple(items)

    def _resolve_execution_plugins(
        self, config: BenchmarkSuiteConfig
    ) -> tuple[TaskAdapter, tuple[ResolvedMetric, ...]]:
        try:
            task = self._registries.tasks.create(config.task_kind, config.task_options)
        except UnknownPluginError:
            raise
        except Exception as error:
            raise _PluginSetupFailure(error, "task_factory") from error
        metrics: list[ResolvedMetric] = []
        for spec in config.metrics:
            try:
                metric = self._registries.metrics.create(
                    spec.metric.name, spec.metric.options
                )
            except UnknownPluginError:
                raise
            except Exception as error:
                raise _PluginSetupFailure(
                    error, "metric_factory", metric_id=spec.metric_id
                ) from error
            metrics.append((spec, metric))
        return task, tuple(metrics)

    def _load_checkpoint(
        self,
        *,
        run_id: str,
        config: BenchmarkSuiteConfig,
        items: tuple[ItemRecord, ...],
    ) -> BenchmarkResult | None:
        if not config.run.resume_enabled:
            return None
        if self._resume_store is None:
            raise ValueError("resume_enabled=True requires a ResumeStore")
        raw_state = self._resume_store.load(run_id)
        if raw_state is None:
            return None
        checkpoint = BenchmarkResult.from_dict(raw_state)
        if checkpoint.run_id != run_id:
            raise ValueError("Resume checkpoint has a different run_id")
        if not _configs_are_resume_compatible(checkpoint.config, config):
            raise ValueError("Resume checkpoint is incompatible with the suite config")
        if checkpoint.items != items:
            raise ValueError(
                "Resume checkpoint items differ from provider output"
            )
        run_keys = [_run_key(record) for record in checkpoint.runs]
        if len(run_keys) != len(set(run_keys)):
            raise ValueError(
                "Resume checkpoint contains duplicate item/model run records"
            )
        known_run_keys = set(run_keys)
        for record in (*checkpoint.predictions, *checkpoint.metrics):
            if _record_key(record) not in known_run_keys:
                raise ValueError(
                    "Resume checkpoint contains output without a run record"
                )
        return checkpoint

    def _build_result(
        self,
        *,
        run_id: str,
        config: BenchmarkSuiteConfig,
        items: tuple[ItemRecord, ...],
        runs: list[RunRecord],
        predictions: list[PredictionRecord],
        metrics: list[MetricRecord],
        errors: list[ExecutionError],
        artifacts: tuple[ArtifactRecord, ...],
    ) -> BenchmarkResult:
        status_counts = {
            status.value: sum(record.status is status for record in runs)
            for status in RunStatus
            if any(record.status is status for record in runs)
        }
        return BenchmarkResult(
            run_id=run_id,
            task_kind=config.task_kind,
            config=config,
            items=items,
            runs=tuple(runs),
            predictions=tuple(predictions),
            metrics=tuple(metrics),
            artifact_manifest=ArtifactManifest(
                run_id=run_id,
                artifacts=artifacts,
            ),
            metadata={
                "errors": [error.to_dict() for error in errors],
                "status_counts": status_counts,
            },
        )

    def _save_checkpoint(self, result: BenchmarkResult) -> None:
        if not result.config.run.resume_enabled:
            return
        if self._resume_store is None:
            raise ValueError("resume_enabled=True requires a ResumeStore")
        state = cast(
            ReadonlyJSONObject,
            freeze_json_value(result.to_dict(), path="resume_state"),
        )
        self._resume_store.save(result.run_id, state)

    def _persist_errors(
        self,
        *,
        run_id: str,
        config: BenchmarkSuiteConfig,
        errors: list[ExecutionError],
        artifacts: tuple[ArtifactRecord, ...],
    ) -> tuple[ArtifactRecord, ...]:
        artifacts = tuple(
            artifact for artifact in artifacts if artifact.kind != "execution_errors"
        )
        if not (
            errors and self._policy.persist_error_artifact and config.artifacts.persist
        ):
            return artifacts
        if self._error_artifact_sink is None:
            raise RuntimeError("Error artifact sink unexpectedly unavailable")
        artifact = self._error_artifact_sink.persist_errors(
            run_id, tuple(errors), config.artifacts
        )
        if not isinstance(artifact, ArtifactRecord):
            raise TypeError("ErrorArtifactSink.persist_errors() must return ArtifactRecord")
        if artifact.kind != "execution_errors":
            raise ValueError(
                "ErrorArtifactSink.persist_errors() must return kind='execution_errors'"
            )
        if any(existing.artifact_id == artifact.artifact_id for existing in artifacts):
            raise ValueError("Error artifact_id conflicts with an existing artifact")
        return artifacts + (artifact,)

    def _raise_setup_failure(
        self,
        failure: _PluginSetupFailure,
        *,
        run_id: str,
        config: BenchmarkSuiteConfig,
        items: tuple[ItemRecord, ...],
        runs: list[RunRecord],
        predictions: list[PredictionRecord],
        metrics: list[MetricRecord],
        errors: list[ExecutionError],
        artifacts: tuple[ArtifactRecord, ...],
    ) -> NoReturn:
        total = len(items) * len(config.models)
        completed = len(runs)
        self._emit("suite_started", current=completed, total=total)
        errors.append(
            _suite_execution_error(
                failure.error,
                run_id=run_id,
                stage=failure.stage,
                dataset_id=failure.dataset_id,
                metric_id=failure.metric_id,
                include_traceback=self._policy.include_traceback,
            )
        )
        artifacts = self._persist_errors(
            run_id=run_id, config=config, errors=errors, artifacts=artifacts
        )
        partial = self._build_result(
            run_id=run_id,
            config=config,
            items=items,
            runs=runs,
            predictions=predictions,
            metrics=metrics,
            errors=errors,
            artifacts=artifacts,
        )
        self._emit(
            "suite_failed",
            current=completed,
            total=total,
            message=str(failure.error),
        )
        # A provider may have yielded only some items. Do not checkpoint setup failures.
        raise SuiteExecutionError(
            f"Suite setup failed during {failure.stage}: {failure.error}", partial
        ) from failure.error

    @staticmethod
    def _append_outcome(
        outcome: ItemExecutionResult,
        *,
        runs: list[RunRecord],
        predictions: list[PredictionRecord],
        metrics: list[MetricRecord],
        errors: list[ExecutionError],
    ) -> None:
        runs.append(outcome.run)
        if outcome.prediction is not None:
            predictions.append(outcome.prediction)
        metrics.extend(outcome.metrics)
        errors.extend(outcome.errors)

    def run(self, config: BenchmarkSuiteConfig) -> BenchmarkResult:
        """Execute one suite and return its standard in-memory result."""

        if not isinstance(config, BenchmarkSuiteConfig):
            raise TypeError("config must be a BenchmarkSuiteConfig")
        if config.run.resume_enabled and self._resume_store is None:
            raise ValueError("resume_enabled=True requires a ResumeStore")
        if (
            self._policy.persist_error_artifact
            and config.artifacts.persist
            and self._error_artifact_sink is None
        ):
            raise ValueError(
                "persist_error_artifact=True requires an ErrorArtifactSink when "
                "ArtifactSpec.persist=True"
            )

        self._validate_plugin_names(config)
        run_id = _new_run_id(config)
        try:
            items = self._load_items(config)
        except _PluginSetupFailure as failure:
            self._raise_setup_failure(
                failure,
                run_id=run_id,
                config=config,
                items=failure.items,
                runs=[],
                predictions=[],
                metrics=[],
                errors=[],
                artifacts=(),
            )
        total = len(items) * len(config.models)
        checkpoint = self._load_checkpoint(
            run_id=run_id,
            config=config,
            items=items,
        )

        if checkpoint is None:
            runs: list[RunRecord] = []
            predictions: list[PredictionRecord] = []
            metric_records: list[MetricRecord] = []
            errors: list[ExecutionError] = []
            artifacts: tuple[ArtifactRecord, ...] = ()
        else:
            runs = list(checkpoint.runs)
            predictions = list(checkpoint.predictions)
            metric_records = list(checkpoint.metrics)
            errors = _errors_from_result(checkpoint)
            artifacts = checkpoint.artifact_manifest.artifacts

        if checkpoint is not None and self._policy.retry_failed_on_resume:
            failed_keys = {
                _run_key(record)
                for record in runs
                if record.status is RunStatus.FAILED
            }
            runs = [record for record in runs if _run_key(record) not in failed_keys]
            predictions = [
                record
                for record in predictions
                if _record_key(record) not in failed_keys
            ]
            metric_records = [
                record
                for record in metric_records
                if _record_key(record) not in failed_keys
            ]
            errors = [
                error
                for error in errors
                if (error.dataset_id, error.model_id, error.item_id)
                not in failed_keys
            ]

        # Checkpoint artifacts describe the previous error set, not this attempt.
        artifacts = tuple(
            artifact for artifact in artifacts if artifact.kind != "execution_errors"
        )

        completed_keys = {_run_key(record) for record in runs}
        completed = len(completed_keys)
        task: TaskAdapter | None = None
        resolved_metrics: tuple[ResolvedMetric, ...] = ()
        if completed < total:
            try:
                task, resolved_metrics = self._resolve_execution_plugins(config)
            except _PluginSetupFailure as failure:
                self._raise_setup_failure(
                    failure,
                    run_id=run_id,
                    config=config,
                    items=items,
                    runs=runs,
                    predictions=predictions,
                    metrics=metric_records,
                    errors=errors,
                    artifacts=artifacts,
                )
        self._emit("suite_started", current=completed, total=total)
        context = ItemExecutionContext(
            task_kind=config.task_kind,
            options=config.task_options,
        )
        stop_after_failure = False

        for model_spec in config.models:
            pending_items = [
                item
                for item in items
                if (item.dataset_id, model_spec.model_id, item.item_id)
                not in completed_keys
            ]
            for item in items:
                key = (item.dataset_id, model_spec.model_id, item.item_id)
                if key not in completed_keys:
                    continue
                self._emit(
                    "item_resumed",
                    current=completed,
                    total=total,
                    metadata={
                        "dataset_id": item.dataset_id,
                        "model_id": model_spec.model_id,
                        "item_id": item.item_id,
                    },
                )
            if not pending_items:
                continue

            model: ModelAdapter | None = None
            model_error: Exception | None = None
            model_error_stage = "model_factory"
            availability: Availability | None = None
            try:
                model = self._registries.models.create(
                    model_spec.adapter.name,
                    model_spec.adapter.options,
                )
            except UnknownPluginError:
                raise
            except Exception as error:
                model_error = error
            try:
                if model_error is None and model is not None:
                    model_error_stage = "availability"
                    availability = model.availability()
                    if not isinstance(availability, Availability):
                        raise TypeError(
                            "ModelAdapter.availability() must return Availability"
                        )
            except Exception as error:
                model_error = error

            for item in pending_items:
                metadata = {
                    "dataset_id": item.dataset_id,
                    "model_id": model_spec.model_id,
                    "item_id": item.item_id,
                }
                self._emit(
                    "item_started",
                    current=completed,
                    total=total,
                    metadata=metadata,
                )
                if model_error is not None:
                    outcome = failed_status_result(
                        model_error,
                        run_id=run_id,
                        stage=model_error_stage,
                        item=item,
                        model_id=model_spec.model_id,
                        include_traceback=self._policy.include_traceback,
                        clock=self._clock,
                    )
                elif availability is not None and not availability.available:
                    status = (
                        RunStatus.SKIPPED
                        if model_spec.optional
                        else RunStatus.NOT_AVAILABLE
                    )
                    outcome = status_result(
                        run_id=run_id,
                        item=item,
                        model_id=model_spec.model_id,
                        status=status,
                        message=availability.reason or "model is unavailable",
                        clock=self._clock,
                    )
                else:
                    if model is None:
                        raise RuntimeError("Model resolution produced no adapter")
                    if task is None:
                        raise RuntimeError("Task resolution produced no adapter")
                    outcome = execute_item(
                        run_id=run_id,
                        task=task,
                        item=item,
                        model=model,
                        model_id=model_spec.model_id,
                        metrics=resolved_metrics,
                        context=context,
                        include_traceback=self._policy.include_traceback,
                        clock=self._clock,
                    )
                self._append_outcome(
                    outcome,
                    runs=runs,
                    predictions=predictions,
                    metrics=metric_records,
                    errors=errors,
                )
                completed += 1
                completed_keys.add(
                    (item.dataset_id, model_spec.model_id, item.item_id)
                )
                partial = self._build_result(
                    run_id=run_id,
                    config=config,
                    items=items,
                    runs=runs,
                    predictions=predictions,
                    metrics=metric_records,
                    errors=errors,
                    artifacts=artifacts,
                )
                self._save_checkpoint(partial)
                self._emit(
                    "item_completed",
                    current=completed,
                    total=total,
                    message=outcome.run.message,
                    metadata={**metadata, "status": outcome.run.status.value},
                )
                if outcome.run.status is RunStatus.FAILED and self._policy.fail_fast:
                    stop_after_failure = True
                    break
            if stop_after_failure:
                break

        artifacts = self._persist_errors(
            run_id=run_id, config=config, errors=errors, artifacts=artifacts
        )

        result = self._build_result(
            run_id=run_id,
            config=config,
            items=items,
            runs=runs,
            predictions=predictions,
            metrics=metric_records,
            errors=errors,
            artifacts=artifacts,
        )
        self._save_checkpoint(result)
        final_kind = "suite_failed" if errors else "suite_completed"
        self._emit(final_kind, current=completed, total=total)
        if stop_after_failure:
            raise SuiteExecutionError(
                "Suite stopped after the first failed item execution",
                result,
            )
        return result


def run_suite(
    config: BenchmarkSuiteConfig,
    registries: PluginRegistries,
    *,
    policy: ExecutionPolicy | None = None,
    progress_hook: ProgressHook | None = None,
    resume_store: ResumeStore | None = None,
    error_artifact_sink: ErrorArtifactSink | None = None,
) -> BenchmarkResult:
    """Run a benchmark suite with the generic ROAST orchestrator."""

    return SuiteOrchestrator(
        registries,
        policy=policy,
        progress_hook=progress_hook,
        resume_store=resume_store,
        error_artifact_sink=error_artifact_sink,
    ).run(config)
