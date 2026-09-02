from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .schema import (
    JSONObject,
    SCHEMA_VERSION,
    SchemaError,
    SchemaMixin,
    boolean_value,
    ensure_json_value,
    ensure_schema_version,
    object_value,
    optional_integer,
    require_schema_version,
    require_string,
)


@dataclass(frozen=True)
class Availability(SchemaMixin):
    """Describe whether a plugin can run in the current environment.

    Attributes:
        available: Whether the plugin is ready for execution.
        reason: Human-readable explanation when execution is unavailable.
        metadata: Consumer-defined JSON details about availability.
        schema_version: Version of the serialized schema.
    """

    available: bool
    reason: str = ""
    metadata: JSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ensure_schema_version(self.schema_version, schema_name="Availability")
        if type(self.available) is not bool:
            raise SchemaError("Availability.available must be a boolean")
        if not isinstance(self.reason, str):
            raise SchemaError("Availability.reason must be a string")
        ensure_json_value(self.metadata, path="Availability.metadata")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Availability":
        if "available" not in data:
            raise SchemaError("Availability.available is required")
        return cls(
            available=boolean_value(
                data, "available", schema_name="Availability", default=False
            ),
            reason=(
                require_string(data, "reason", schema_name="Availability")
                if "reason" in data
                else ""
            ),
            metadata=object_value(data, "metadata", schema_name="Availability"),
            schema_version=require_schema_version(data, schema_name="Availability"),
        )


@dataclass(frozen=True)
class ProgressEvent(SchemaMixin):
    """Represent a task-neutral progress notification.

    Attributes:
        kind: Stable event kind understood by the event producer.
        current: Current completed-unit count, when known.
        total: Total unit count, when known.
        message: Human-readable progress description.
        metadata: Consumer-defined JSON details about the event.
        schema_version: Version of the serialized schema.
    """

    kind: str
    current: int | None = None
    total: int | None = None
    message: str = ""
    metadata: JSONObject = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ensure_schema_version(self.schema_version, schema_name="ProgressEvent")
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise SchemaError("ProgressEvent.kind must be a non-empty string")
        if self.current is not None and type(self.current) is not int:
            raise SchemaError("ProgressEvent.current must be an integer or null")
        if self.total is not None and type(self.total) is not int:
            raise SchemaError("ProgressEvent.total must be an integer or null")
        if self.current is not None and self.current < 0:
            raise SchemaError("ProgressEvent.current must not be negative")
        if self.total is not None and self.total < 0:
            raise SchemaError("ProgressEvent.total must not be negative")
        if not isinstance(self.message, str):
            raise SchemaError("ProgressEvent.message must be a string")
        ensure_json_value(self.metadata, path="ProgressEvent.metadata")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgressEvent":
        return cls(
            kind=require_string(data, "kind", schema_name="ProgressEvent"),
            current=optional_integer(data, "current", schema_name="ProgressEvent"),
            total=optional_integer(data, "total", schema_name="ProgressEvent"),
            message=(
                require_string(data, "message", schema_name="ProgressEvent")
                if "message" in data
                else ""
            ),
            metadata=object_value(data, "metadata", schema_name="ProgressEvent"),
            schema_version=require_schema_version(data, schema_name="ProgressEvent"),
        )
