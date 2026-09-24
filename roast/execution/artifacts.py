from typing import Protocol, runtime_checkable

from roast.core.config import ArtifactSpec
from roast.core.records import ArtifactRecord
from roast.execution.errors import ExecutionError


@runtime_checkable
class ErrorArtifactSink(Protocol):
    """Persist errors and return an artifact with kind 'execution_errors'."""

    def persist_errors(
        self,
        run_id: str,
        errors: tuple[ExecutionError, ...],
        spec: ArtifactSpec,
    ) -> ArtifactRecord: ...
