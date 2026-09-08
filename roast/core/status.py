from enum import Enum


class RunStatus(str, Enum):
    """Enumerate task-neutral lifecycle states for benchmark records."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_AVAILABLE = "not_available"
