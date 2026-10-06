from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from roast.core.config import BenchmarkSuiteConfig
from roast.core.schema import (
    ReadonlyJSONObject,
    SCHEMA_VERSION,
    freeze_json_value,
    to_plain_data,
)
from roast.plugins.errors import ManifestError
from roast.plugins.registry import PresetRegistry


MANIFEST_FORMAT = "roast_manifest@1"


def _merge_objects(
    base: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    """Recursively merge JSON objects; arrays and scalar values are replaced."""

    merged = dict(base)
    for key, value in overrides.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_objects(current, value)
        else:
            merged[key] = value
    return merged


def _plain_object(value: Mapping[str, Any]) -> dict[str, Any]:
    plain = to_plain_data(value)
    if not isinstance(plain, dict):  # Defensive: mappings always serialize as objects.
        raise ManifestError("Manifest options must serialize to a JSON object")
    return plain


@dataclass(frozen=True)
class SuiteManifest:
    """Select either an inline suite config or a registered preset."""

    suite: BenchmarkSuiteConfig | None = None
    preset: str | None = None
    preset_options: ReadonlyJSONObject = field(default_factory=dict)
    overrides: ReadonlyJSONObject = field(default_factory=dict)
    format: str = MANIFEST_FORMAT
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.format != MANIFEST_FORMAT:
            raise ManifestError(
                f"Unsupported manifest format {self.format!r}; expected {MANIFEST_FORMAT!r}"
            )
        if self.schema_version != SCHEMA_VERSION:
            raise ManifestError(
                f"Unsupported SuiteManifest schema_version {self.schema_version!r}"
            )
        if (self.suite is None) == (self.preset is None):
            raise ManifestError("Manifest must define exactly one of 'suite' or 'preset'")
        if self.suite is not None and not isinstance(self.suite, BenchmarkSuiteConfig):
            raise ManifestError("Manifest suite must be a BenchmarkSuiteConfig")
        if self.preset is not None and (not isinstance(self.preset, str) or not self.preset.strip()):
            raise ManifestError("Manifest preset must be a non-empty string")
        if self.suite is not None and self.overrides:
            raise ManifestError("Manifest 'overrides' may only be used with 'preset'")
        object.__setattr__(self, "preset_options", freeze_json_value(dict(self.preset_options)))
        object.__setattr__(self, "overrides", freeze_json_value(dict(self.overrides)))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SuiteManifest":
        if not isinstance(data, Mapping):
            raise ManifestError("Manifest root must be an object")
        allowed = {
            "format",
            "schema_version",
            "suite",
            "preset",
            "preset_options",
            "overrides",
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ManifestError(f"Unknown manifest fields: {', '.join(unknown)}")
        suite_value = data.get("suite")
        if suite_value is not None and not isinstance(suite_value, Mapping):
            raise ManifestError("Manifest 'suite' must be an object")
        options = data.get("preset_options", {})
        if not isinstance(options, Mapping):
            raise ManifestError("Manifest 'preset_options' must be an object")
        overrides = data.get("overrides", {})
        if not isinstance(overrides, Mapping):
            raise ManifestError("Manifest 'overrides' must be an object")
        return cls(
            suite=(
                BenchmarkSuiteConfig.from_dict(suite_value)
                if suite_value is not None
                else None
            ),
            preset=data.get("preset"),
            preset_options=dict(options),
            overrides=dict(overrides),
            format=data.get("format", ""),
            schema_version=data.get("schema_version", -1),
        )

    def resolve(self, presets: PresetRegistry | None = None) -> BenchmarkSuiteConfig:
        if self.suite is not None:
            return self.suite
        if presets is None:
            raise ManifestError(
                f"Manifest selects preset {self.preset!r}, but no PresetRegistry was supplied"
            )
        config = presets.create(self.preset or "", self.preset_options)
        if not isinstance(config, BenchmarkSuiteConfig):
            raise ManifestError(
                f"Preset {self.preset!r} did not return a BenchmarkSuiteConfig"
            )
        if not self.overrides:
            return config
        return BenchmarkSuiteConfig.from_dict(
            _merge_objects(config.to_dict(), _plain_object(self.overrides))
        )

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "format": self.format,
            "schema_version": self.schema_version,
        }
        if self.suite is not None:
            value["suite"] = self.suite.to_dict()
        else:
            value["preset"] = self.preset
            value["preset_options"] = _plain_object(self.preset_options)
            if self.overrides:
                value["overrides"] = _plain_object(self.overrides)
        return value


def _load_payload(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ManifestError(f"Cannot read manifest {path}: {error}") from error
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as error:
            raise ManifestError(
                "YAML manifests require the optional 'yaml' dependency; "
                "install roast[yaml] or use JSON"
            ) from error
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise ManifestError(f"Invalid YAML manifest: {error}") from error
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ManifestError(f"Invalid JSON manifest: {error}") from error


def load_manifest(
    path: str | Path,
    presets: PresetRegistry | None = None,
) -> BenchmarkSuiteConfig:
    """Load, validate, and resolve a JSON or YAML suite manifest."""

    manifest_path = Path(path)
    payload = _load_payload(manifest_path)
    if not isinstance(payload, Mapping):
        raise ManifestError("Manifest root must be an object")
    return SuiteManifest.from_dict(payload).resolve(presets)
