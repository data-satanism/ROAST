from __future__ import annotations

import ast
from pathlib import Path

import roast
from roast.core.config import BenchmarkSuiteConfig
from roast.core.records import ItemRecord, MetricRecord, PredictionRecord, RunRecord
from roast.plugins.registry import TaskKindRegistry
from roast.protocols.dataset import DatasetProvider
from roast.protocols.hooks import ProgressHook, ResumeStore
from roast.protocols.metric import Metric
from roast.protocols.model import ModelAdapter
from roast.protocols.task import TaskAdapter


ROOT = Path(__file__).resolve().parents[2]


def test_core_has_no_reference_framework_imports() -> None:
    forbidden = ("fedot_ind", "benchmark.industrial")
    violations: list[str] = []
    for path in (ROOT / "roast").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            for module in modules:
                if module.startswith(forbidden):
                    violations.append(f"{path}: {module}")
    assert violations == []


def test_public_contracts_are_importable_from_their_owning_modules() -> None:
    contracts = (
        BenchmarkSuiteConfig,
        DatasetProvider,
        ItemRecord,
        Metric,
        MetricRecord,
        ModelAdapter,
        PredictionRecord,
        ProgressHook,
        ResumeStore,
        RunRecord,
        TaskAdapter,
        TaskKindRegistry,
    )
    assert all(contract is not None for contract in contracts)


def test_reference_tree_is_ignored_by_git_configuration() -> None:
    ignore_file = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/Fedot-Industrial-ref/" in ignore_file


def test_docs_name_mandatory_extensions_and_mental_model() -> None:
    docs = (ROOT / "docs" / "extensions.md").read_text(encoding="utf-8")
    for term in ("DatasetProvider", "ModelAdapter", "Metric", "TaskAdapter"):
        assert term in docs
    assert "config -> registered plugin contracts -> orchestrator -> artifacts -> compare" in docs
    assert "schema_version" in docs
    assert "missing" in docs
    assert "unsupported" in docs


def test_future_runtime_apis_are_not_published() -> None:
    future_names = {"Orchestrator", "TaskExecutionContext", "TaskResult", "compare_metric"}
    assert all(not hasattr(roast, name) for name in future_names)


def test_package_initializers_are_empty() -> None:
    initializers = [*(ROOT / "roast").rglob("__init__.py"), ROOT / "examples" / "__init__.py"]
    for path in initializers:
        assert path.read_text(encoding="utf-8").strip() == ""


def test_future_runtime_packages_are_not_present() -> None:
    assert not (ROOT / "roast" / "execution").exists()
    assert not (ROOT / "roast" / "comparison").exists()
