"""Public integration surface for ROAST."""

from roast.comparison.comparison import (
    build_comparison_table,
    build_leaderboard,
    build_mean_ranks,
    build_pairwise_deltas,
    load_artifact_root,
    load_run_directory,
    load_showcase,
)
from roast.core.config import (
    ArtifactSpec,
    BenchmarkSuiteConfig,
    DatasetSpec,
    MetricSpec,
    ModelSpec,
    PluginSpec,
    RunSpec,
)
from roast.execution.orchestrator import PluginRegistries, run_suite
from roast.execution.persistence import FileSystemRunStore
from roast.manifests import SuiteManifest, load_manifest
from roast.plugins.metrics import standard_metric_registry
from roast.plugins.registry import (
    DatasetProviderRegistry,
    MetricDirection,
    MetricRegistry,
    ModelAdapterRegistry,
    PresetRegistry,
    TaskKindRegistry,
)

__all__ = (
    "ArtifactSpec",
    "BenchmarkSuiteConfig",
    "DatasetProviderRegistry",
    "DatasetSpec",
    "FileSystemRunStore",
    "MetricDirection",
    "MetricRegistry",
    "MetricSpec",
    "ModelAdapterRegistry",
    "ModelSpec",
    "PluginRegistries",
    "PluginSpec",
    "PresetRegistry",
    "RunSpec",
    "SuiteManifest",
    "TaskKindRegistry",
    "build_comparison_table",
    "build_leaderboard",
    "build_mean_ranks",
    "build_pairwise_deltas",
    "load_artifact_root",
    "load_manifest",
    "load_run_directory",
    "load_showcase",
    "run_suite",
    "standard_metric_registry",
)
