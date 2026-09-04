from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, TypeAlias, cast


SCHEMA_VERSION = 1

JSONScalar: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONScalar | list[Any] | dict[str, Any]
JSONObject: TypeAlias = dict[str, JSONValue]
ReadonlyJSONValue: TypeAlias = (
    JSONScalar
    | tuple[Any, ...]
    | Mapping[str, Any]
)
ReadonlyJSONObject: TypeAlias = Mapping[str, ReadonlyJSONValue]


class SchemaError(ValueError):
    """Raised when public data does not conform to the ROAST JSON schema."""


def ensure_schema_version(value: object, *, schema_name: str) -> None:
    if type(value) is not int or value != SCHEMA_VERSION:
        raise SchemaError(
            f"Unsupported {schema_name} schema_version {value!r}; "
            f"expected {SCHEMA_VERSION}."
        )


def ensure_json_value(value: object, *, path: str = "value") -> None:
    """Validate strict JSON compatibility, including finite numeric values."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SchemaError(f"{path} must contain only finite JSON numbers")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            ensure_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SchemaError(f"{path} contains a non-string key: {key!r}")
            ensure_json_value(item, path=f"{path}.{key}")
        return
    raise SchemaError(f"{path} contains a non-JSON value: {type(value).__name__}")


def require_schema_version(data: Mapping[str, Any], *, schema_name: str) -> int:
    if "schema_version" not in data:
        raise SchemaError(f"{schema_name}.schema_version is required")
    value = data["schema_version"]
    ensure_schema_version(value, schema_name=schema_name)
    return cast(int, value)


def require_string(data: Mapping[str, Any], key: str, *, schema_name: str) -> str:
    if key not in data:
        raise SchemaError(f"{schema_name}.{key} is required")
    value = data[key]
    if not isinstance(value, str):
        raise SchemaError(f"{schema_name}.{key} must be a string")
    return value


def optional_string(
    data: Mapping[str, Any],
    key: str,
    *,
    schema_name: str,
    default: str | None = None,
) -> str | None:
    value = data.get(key, default)
    if value is not None and not isinstance(value, str):
        raise SchemaError(f"{schema_name}.{key} must be a string or null")
    return value


def boolean_value(
    data: Mapping[str, Any], key: str, *, schema_name: str, default: bool
) -> bool:
    value = data.get(key, default)
    if type(value) is not bool:
        raise SchemaError(f"{schema_name}.{key} must be a boolean")
    return cast(bool, value)


def integer_value(
    data: Mapping[str, Any], key: str, *, schema_name: str, default: int
) -> int:
    value = data.get(key, default)
    if type(value) is not int:
        raise SchemaError(f"{schema_name}.{key} must be an integer")
    return cast(int, value)


def optional_integer(
    data: Mapping[str, Any], key: str, *, schema_name: str
) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if type(value) is not int:
        raise SchemaError(f"{schema_name}.{key} must be an integer or null")
    return cast(int, value)


def number_or_none(data: Mapping[str, Any], key: str, *, schema_name: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaError(f"{schema_name}.{key} must be a number or null")
    number = float(value)
    ensure_json_value(number, path=f"{schema_name}.{key}")
    return number


def array_value(
    data: Mapping[str, Any],
    key: str,
    *,
    schema_name: str,
    required: bool = False,
) -> list[Any]:
    if key not in data:
        if required:
            raise SchemaError(f"{schema_name}.{key} is required")
        return []
    value = data[key]
    if not isinstance(value, list):
        raise SchemaError(f"{schema_name}.{key} must be an array")
    return value


def object_value(
    data: Mapping[str, Any],
    key: str,
    *,
    schema_name: str,
    required: bool = False,
) -> dict[str, Any]:
    if key not in data:
        if required:
            raise SchemaError(f"{schema_name}.{key} is required")
        return {}
    value = data[key]
    if not isinstance(value, Mapping):
        raise SchemaError(f"{schema_name}.{key} must be an object")
    ensure_json_value(value, path=f"{schema_name}.{key}")
    return dict(value)


def required_json_value(
    data: Mapping[str, Any], key: str, *, schema_name: str
) -> JSONValue:
    if key not in data:
        raise SchemaError(f"{schema_name}.{key} is required")
    value = data[key]
    ensure_json_value(value, path=f"{schema_name}.{key}")
    return cast(JSONValue, value)


def optional_json_value(
    data: Mapping[str, Any], key: str, *, schema_name: str
) -> JSONValue:
    value = data.get(key)
    ensure_json_value(value, path=f"{schema_name}.{key}")
    return cast(JSONValue, value)


def freeze_json_value(
    value: JSONValue | ReadonlyJSONValue,
    *,
    path: str = "value",
) -> ReadonlyJSONValue:
    """Return an immutable defensive copy of a JSON-compatible value."""
    ensure_json_value(value, path=path)
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: freeze_json_value(item, path=f"{path}.{key}") for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            freeze_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    return cast(JSONScalar, value)


def _frozen_json(value: object, *, path: str) -> ReadonlyJSONValue:
    ensure_json_value(value, path=path)
    return freeze_json_value(cast(ReadonlyJSONValue, value), path=path)


def _frozen_object(value: Mapping[str, Any], *, path: str) -> ReadonlyJSONObject:
    if not isinstance(value, Mapping):
        raise SchemaError(f"{path} must be an object")
    frozen = freeze_json_value(dict(value), path=path)
    return cast(ReadonlyJSONObject, frozen)


def _name(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{field_name} must be a non-empty string")


def _mapping(value: object, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaError(f"{path} must be an object")
    return value


def _string_default(
    data: Mapping[str, Any], key: str, *, schema_name: str, default: str
) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise SchemaError(f"{schema_name}.{key} must be a string")
    return value


def to_plain_data(value: Any) -> JSONValue:
    """Convert a public ROAST value to strict, JSON-friendly Python data."""
    if is_dataclass(value):
        return to_plain_data({item.name: getattr(value, item.name) for item in fields(value)})
    if isinstance(value, Enum):
        return to_plain_data(value.value)
    if isinstance(value, Mapping):
        for key in value:
            if not isinstance(key, str):
                raise SchemaError(f"value contains a non-string key: {key!r}")
        plain = {key: to_plain_data(item) for key, item in value.items()}
        ensure_json_value(plain)
        return plain
    if isinstance(value, (list, tuple)):
        plain_list = [to_plain_data(item) for item in value]
        ensure_json_value(plain_list)
        return plain_list
    ensure_json_value(value)
    return value


class SchemaMixin:
    """JSON serialization shared by all public schema objects."""

    def to_dict(self) -> JSONObject:
        plain = to_plain_data(self)
        if not isinstance(plain, dict):
            raise SchemaError("A schema object must serialize to a JSON object")
        return plain
