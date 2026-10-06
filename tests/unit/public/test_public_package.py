from examples.toy_plugins import (
    build_registries,
    classification_config,
    forecasting_config,
)
from examples.third_party_template.plugin import (
    build_config as build_template_config,
    register_plugins as register_template_plugins,
)
from roast import (
    FileSystemRunStore,
    PluginRegistries,
    build_leaderboard,
    run_suite,
)
from roast.plugins.registry import (
    DatasetProviderRegistry,
    MetricRegistry,
    ModelAdapterRegistry,
    TaskKindRegistry,
)


def test_short_public_imports_and_classification_toy_path(tmp_path) -> None:
    result = run_suite(
        classification_config(str(tmp_path)),
        PluginRegistries(*build_registries()),
    )
    FileSystemRunStore(tmp_path).persist_result(result)
    assert [record.value for record in result.metrics] == [1.0, 1.0]
    assert build_leaderboard(result)[0]["model_id"] == "majority"
    assert (tmp_path / "runs" / result.run_id / "manifest.json").is_file()


def test_forecasting_toy_path_is_dependency_free() -> None:
    result = run_suite(
        forecasting_config(persist=False),
        PluginRegistries(*build_registries()),
    )
    assert [record.value for record in result.metrics] == [0.0, 0.0]


def test_third_party_template_is_runnable(tmp_path) -> None:
    registries = PluginRegistries(
        DatasetProviderRegistry(),
        ModelAdapterRegistry(),
        MetricRegistry(),
        TaskKindRegistry(),
    )
    register_template_plugins(registries)

    result = run_suite(build_template_config(str(tmp_path)), registries)
    FileSystemRunStore(tmp_path).persist_result(result)

    assert [record.value for record in result.metrics] == [0.0, 0.0, 0.0]
    assert (tmp_path / "runs" / result.run_id / "manifest.json").is_file()
