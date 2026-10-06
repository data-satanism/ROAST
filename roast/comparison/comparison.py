from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import mean
from typing import Any

from roast.core.records import BenchmarkResult, MetricRecord
from roast.core.schema import SCHEMA_VERSION
from roast.core.status import RunStatus
from roast.plugins.registry import MetricDirection


SHOWCASE_FORMAT = "roast_showcase@1"


def load_run_directory(path: str | Path) -> BenchmarkResult:
    """Load a run from its portable BMF-106 directory."""

    checkpoint = Path(path) / "checkpoint.json"
    try:
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"Run directory has no checkpoint.json: {path}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("checkpoint.json must contain an object")
    return BenchmarkResult.from_dict(payload)


def load_artifact_root(path: str | Path) -> tuple[BenchmarkResult, ...]:
    """Load all registered runs from an artifact root in registry order."""

    root = Path(path)
    registry = root / "_registry" / "run_registry.jsonl"
    if not registry.exists():
        raise ValueError(f"Artifact root has no run registry: {root}")
    results: list[BenchmarkResult] = []
    for line_number, line in enumerate(registry.read_text("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        entry = json.loads(line)
        if not isinstance(entry, Mapping) or not isinstance(entry.get("run_id"), str):
            raise ValueError(f"Invalid run registry entry at line {line_number}")
        results.append(load_run_directory(root / "runs" / entry["run_id"]))
    return tuple(results)


def _selected_metric(result: BenchmarkResult, metric_id: str | None) -> str:
    selected = metric_id or result.config.run.primary_metric
    if selected is None:
        if len(result.config.metrics) != 1:
            raise ValueError("metric_id is required when the run has no unique primary metric")
        selected = result.config.metrics[0].metric_id
    if selected not in {spec.metric_id for spec in result.config.metrics}:
        raise ValueError(f"Unknown metric_id {selected!r} for run {result.run_id!r}")
    return selected


def _direction(records: Iterable[MetricRecord]) -> MetricDirection:
    values = {record.metadata.get("direction") for record in records}
    values.discard(None)
    if len(values) != 1:
        raise ValueError("Metric records must declare one consistent ranking direction")
    try:
        return MetricDirection(values.pop())
    except (ValueError, TypeError) as error:
        raise ValueError("Metric records contain an invalid ranking direction") from error


def build_leaderboard(
    result: BenchmarkResult,
    metric_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Aggregate one run into stable, deterministically ranked model rows."""

    selected = _selected_metric(result, metric_id)
    records = tuple(
        record for record in result.metrics
        if record.metric_id == selected and record.status is RunStatus.SUCCESS and record.value is not None
    )
    if not records:
        return ()
    direction = _direction(records)
    grouped: dict[str, list[float]] = defaultdict(list)
    for record in records:
        grouped[record.model_id].append(record.value)  # type: ignore[arg-type]
    descending = direction is MetricDirection.MAXIMIZE
    ordered = sorted(
        ((model_id, mean(values), len(values)) for model_id, values in grouped.items()),
        key=lambda value: ((-value[1] if descending else value[1]), value[0]),
    )
    return tuple({
        "run_id": result.run_id,
        "model_id": model_id,
        "metric_id": selected,
        "score": score,
        "direction": direction.value,
        "observations": observations,
        "rank": rank,
    } for rank, (model_id, score, observations) in enumerate(ordered, start=1))


def build_mean_ranks(
    results: Iterable[BenchmarkResult],
    metric_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Average each model's leaderboard rank across multiple runs."""

    ranks: dict[str, list[int]] = defaultdict(list)
    for result in results:
        for row in build_leaderboard(result, metric_id):
            ranks[row["model_id"]].append(row["rank"])
    ordered = sorted(
        ((model_id, mean(values), len(values)) for model_id, values in ranks.items()),
        key=lambda value: (value[1], value[0]),
    )
    return tuple({
        "model_id": model_id,
        "mean_rank": rank,
        "run_count": count,
    } for model_id, rank, count in ordered)


def build_pairwise_deltas(
    left: BenchmarkResult,
    right: BenchmarkResult,
    metric_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Compare aligned metric records and report raw delta plus improvement."""

    left_metric = _selected_metric(left, metric_id)
    right_metric = _selected_metric(right, metric_id or left_metric)
    if left_metric != right_metric:
        raise ValueError("Pairwise comparison requires the same metric_id")
    left_records = {
        (record.dataset_id, record.model_id, record.item_id): record
        for record in left.metrics
        if record.metric_id == left_metric and record.status is RunStatus.SUCCESS and record.value is not None
    }
    right_records = {
        (record.dataset_id, record.model_id, record.item_id): record
        for record in right.metrics
        if record.metric_id == right_metric and record.status is RunStatus.SUCCESS and record.value is not None
    }
    shared = sorted(set(left_records) & set(right_records))
    if not shared:
        return ()
    direction = _direction(left_records[key] for key in shared)
    if _direction(right_records[key] for key in shared) is not direction:
        raise ValueError("Compared runs declare different metric directions")
    rows = []
    for dataset_id, model_id, item_id in shared:
        left_value = left_records[(dataset_id, model_id, item_id)].value
        right_value = right_records[(dataset_id, model_id, item_id)].value
        assert left_value is not None and right_value is not None
        delta = right_value - left_value
        improvement = delta if direction is MetricDirection.MAXIMIZE else -delta
        rows.append({
            "left_run_id": left.run_id,
            "right_run_id": right.run_id,
            "dataset_id": dataset_id,
            "model_id": model_id,
            "item_id": item_id,
            "metric_id": left_metric,
            "direction": direction.value,
            "left_value": left_value,
            "right_value": right_value,
            "delta": delta,
            "improvement": improvement,
        })
    return tuple(rows)


def build_comparison_table(
    results: Iterable[BenchmarkResult],
    metric_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return stable leaderboard rows for multiple runs."""

    return tuple(
        row
        for result in results
        for row in build_leaderboard(result, metric_id)
    )


@dataclass(frozen=True)
class ShowcaseRun:
    artifact_root: str
    run_id: str
    display_name: str


def load_showcase(path: str | Path) -> tuple[tuple[str, BenchmarkResult], ...]:
    """Load runs selected by a config-driven showcase manifest."""

    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Showcase manifest root must be an object")
    if payload.get("format") != SHOWCASE_FORMAT or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Showcase manifest must use {SHOWCASE_FORMAT!r} and schema_version 1")
    raw_runs = payload.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ValueError("Showcase manifest runs must be a non-empty array")
    loaded = []
    for index, raw in enumerate(raw_runs):
        if not isinstance(raw, Mapping):
            raise ValueError(f"Showcase run {index} must be an object")
        try:
            source = ShowcaseRun(
                artifact_root=str(raw["artifact_root"]),
                run_id=str(raw["run_id"]),
                display_name=str(raw["display_name"]),
            )
        except KeyError as error:
            raise ValueError(f"Showcase run {index} is missing {error.args[0]!r}") from error
        root = Path(source.artifact_root)
        if not root.is_absolute():
            root = manifest_path.parent / root
        loaded.append((source.display_name, load_run_directory(root / "runs" / source.run_id)))
    return tuple(loaded)
