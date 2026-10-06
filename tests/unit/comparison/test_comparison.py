from dataclasses import replace
import csv
from io import StringIO
import json

from examples.custom_plugins import build_config, build_registries
from roast.comparison.comparison import (
    SHOWCASE_FORMAT,
    build_comparison_table,
    build_leaderboard,
    build_mean_ranks,
    build_pairwise_deltas,
    load_artifact_root,
    load_showcase,
)
from roast.core.config import ModelSpec, PluginSpec, RunSpec
from roast.execution.orchestrator import PluginRegistries, run_suite
from roast.execution.persistence import FileSystemRunStore


def make_result(*, triple_factor: int, run_name: str):
    config = replace(
        build_config(),
        models=(
            ModelSpec("double", PluginSpec("example.scale", {"factor": 2})),
            ModelSpec("challenger", PluginSpec("example.scale", {"factor": triple_factor})),
        ),
        run=RunSpec(run_name=run_name, primary_metric="absolute_error"),
    )
    return run_suite(config, PluginRegistries(*build_registries()))


def test_leaderboard_mean_ranks_and_comparison_table_are_stable() -> None:
    first = make_result(triple_factor=3, run_name="first")
    second = make_result(triple_factor=4, run_name="second")

    leaderboard = build_leaderboard(first)
    assert [row["model_id"] for row in leaderboard] == ["double", "challenger"]
    assert [row["rank"] for row in leaderboard] == [1, 2]
    assert leaderboard[0]["direction"] == "minimize"
    assert len(build_comparison_table((first, second))) == 4
    assert build_mean_ranks((first, second)) == (
        {"model_id": "double", "mean_rank": 1, "run_count": 2},
        {"model_id": "challenger", "mean_rank": 2, "run_count": 2},
    )


def test_leaderboard_csv_and_markdown_snapshots_have_stable_sorting() -> None:
    rows = tuple(
        {**row, "run_id": "<run-id>"}
        for row in build_leaderboard(make_result(triple_factor=3, run_name="snapshot"))
    )
    columns = (
        "run_id",
        "model_id",
        "metric_id",
        "score",
        "direction",
        "observations",
        "rank",
    )

    csv_output = StringIO()
    writer = csv.DictWriter(csv_output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    assert csv_output.getvalue() == (
        "run_id,model_id,metric_id,score,direction,observations,rank\n"
        "<run-id>,double,absolute_error,0.0,minimize,3,1\n"
        "<run-id>,challenger,absolute_error,2.0,minimize,3,2\n"
    )

    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(row[column]) for column in columns) + " |"
        for row in rows
    ]
    markdown = "\n".join((header, separator, *body)) + "\n"
    assert markdown == (
        "| run_id | model_id | metric_id | score | direction | observations | rank |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| <run-id> | double | absolute_error | 0.0 | minimize | 3 | 1 |\n"
        "| <run-id> | challenger | absolute_error | 2.0 | minimize | 3 | 2 |\n"
    )


def test_pairwise_deltas_report_direction_aware_improvement() -> None:
    better = make_result(triple_factor=3, run_name="better")
    worse = make_result(triple_factor=4, run_name="worse")

    rows = build_pairwise_deltas(better, worse)
    challenger = [row for row in rows if row["model_id"] == "challenger"]
    assert len(challenger) == 3
    assert all(row["delta"] > 0 for row in challenger)
    assert all(row["improvement"] < 0 for row in challenger)


def test_artifact_root_and_showcase_ingestion_need_only_json(tmp_path) -> None:
    result = make_result(triple_factor=3, run_name="stored")
    store = FileSystemRunStore(tmp_path / "artifacts")
    store.persist_result(result)
    assert load_artifact_root(store.root)[0].run_id == result.run_id

    showcase_path = tmp_path / "showcase.json"
    showcase_path.write_text(json.dumps({
        "format": SHOWCASE_FORMAT,
        "schema_version": 1,
        "runs": [{
            "artifact_root": "artifacts",
            "run_id": result.run_id,
            "display_name": "Toy run",
        }],
    }), encoding="utf-8")
    loaded = load_showcase(showcase_path)
    assert loaded[0][0] == "Toy run"
    assert loaded[0][1].run_id == result.run_id
