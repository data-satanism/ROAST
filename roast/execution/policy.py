from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionPolicy:
    """Control task-neutral suite failure and checkpoint behavior.

    Attributes:
        fail_fast: Stop the suite after the first failed item execution.
        include_traceback: Include formatted tracebacks in aggregated errors.
        persist_error_artifact: Ask the configured error sink to persist errors.
        retry_failed_on_resume: Re-run item/model pairs that previously failed.
    """

    fail_fast: bool = False
    include_traceback: bool = False
    persist_error_artifact: bool = False
    retry_failed_on_resume: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "fail_fast",
            "include_traceback",
            "persist_error_artifact",
            "retry_failed_on_resume",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise TypeError(f"ExecutionPolicy.{field_name} must be a boolean")
