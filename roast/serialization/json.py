from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roast.core.config import BenchmarkSuiteConfig
from roast.core.records import BenchmarkResult
from roast.core.schema import JSONValue, ReadonlyJSONValue, SchemaMixin, to_plain_data


def dumps(
    value: SchemaMixin | JSONValue | ReadonlyJSONValue,
    *,
    indent: int | None = 2,
) -> str:
    """Serialize ROAST contract data as strict JSON."""
    return json.dumps(
        to_plain_data(value),
        indent=indent,
        ensure_ascii=False,
        allow_nan=False,
    )


def dump(
    value: SchemaMixin | JSONValue | ReadonlyJSONValue,
    path: str | Path,
    *,
    indent: int | None = 2,
) -> None:
    """Write one versioned contract object without defining an artifact layout."""
    Path(path).write_text(dumps(value, indent=indent), encoding="utf-8")


def load_config(path: str | Path) -> BenchmarkSuiteConfig:
    payload: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("A benchmark config must be a JSON object")
    return BenchmarkSuiteConfig.from_dict(payload)


def load_result(path: str | Path) -> BenchmarkResult:
    payload: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("A benchmark result must be a JSON object")
    return BenchmarkResult.from_dict(payload)
