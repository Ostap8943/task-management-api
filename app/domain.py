from datetime import UTC, date, datetime
from enum import StrEnum


class Status(StrEnum):
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    CANCELLED = "cancelled"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


TRANSITIONS = {
    Status.BACKLOG: frozenset({Status.IN_PROGRESS, Status.CANCELLED}),
    Status.IN_PROGRESS: frozenset({Status.REVIEW, Status.CANCELLED}),
    Status.REVIEW: frozenset({Status.DONE}),
    Status.DONE: frozenset(),
    Status.CANCELLED: frozenset(),
}
ACTIVE_STATUSES = (Status.BACKLOG, Status.IN_PROGRESS, Status.REVIEW)
LOCKED_ASSIGNEE_STATUSES = (Status.REVIEW, Status.DONE)
ACTIVE_TASK_LIMIT = 10


def today_utc() -> date:
    return datetime.now(UTC).date()
