from __future__ import annotations

import argparse
from importlib import import_module
import json
from pathlib import Path
from typing import Any

from roast.execution.orchestrator import PluginRegistries, run_suite
from roast.execution.persistence import FileSystemRunStore
from roast.manifests import load_manifest
from roast.plugins.registry import PresetRegistry
from roast.plugins.registry import (
    DatasetProviderRegistry,
    MetricRegistry,
    ModelAdapterRegistry,
    TaskKindRegistry,
)
from roast.serialization.json import dumps


def _empty_registries() -> PluginRegistries:
    return PluginRegistries(
        DatasetProviderRegistry(), ModelAdapterRegistry(), MetricRegistry(), TaskKindRegistry()
    )


def _load_plugins(module_names: list[str]) -> tuple[PluginRegistries, PresetRegistry]:
    registries = _empty_registries()
    presets = PresetRegistry()
    for module_name in module_names:
        module = import_module(module_name)
        if hasattr(module, "register_plugins"):
            module.register_plugins(registries)
        elif hasattr(module, "build_registries"):
            registries = PluginRegistries(*module.build_registries())
        else:
            raise ValueError(
                f"Plugin module {module_name!r} must define register_plugins(registries) "
                "or build_registries()"
            )
        if hasattr(module, "register_presets"):
            module.register_presets(presets)
    return registries, presets


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="roast", description="Run framework-neutral benchmark suites")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="execute a versioned suite manifest")
    run.add_argument("--manifest", required=True, type=Path)
    run.add_argument("--plugin", action="append", default=[], metavar="MODULE")

    resolve = subparsers.add_parser("resolve-manifest", help="print a validated suite config")
    resolve.add_argument("--manifest", required=True, type=Path)
    resolve.add_argument("--plugin", action="append", default=[], metavar="MODULE")

    plugins = subparsers.add_parser("plugins", help="inspect plugin registries")
    plugins_subparsers = plugins.add_subparsers(dest="plugins_command", required=True)
    listing = plugins_subparsers.add_parser("list", help="list registered plugin names")
    listing.add_argument("--plugin", action="append", default=[], metavar="MODULE")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    registries, presets = _load_plugins(args.plugin)
    if args.command == "plugins":
        print(json.dumps({
            "datasets": registries.datasets.names(),
            "models": registries.models.names(),
            "metrics": registries.metrics.names(),
            "tasks": registries.tasks.names(),
            "presets": presets.names(),
        }, indent=2))
        return 0

    config = load_manifest(args.manifest, presets)
    if args.command == "resolve-manifest":
        print(dumps(config))
        return 0

    store = (
        FileSystemRunStore.from_artifact_spec(config.artifacts)
        if config.run.resume_enabled or config.artifacts.persist
        else None
    )
    result = run_suite(
        config,
        registries,
        resume_store=store if config.run.resume_enabled else None,
    )
    if store is not None and not config.run.resume_enabled and config.artifacts.persist:
        store.persist_result(result)
    print(dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
