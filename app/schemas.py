from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Generic, Self, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .domain import Priority, Status

def reject_null_character(value: str) -> str:
    if "\x00" in value:
        raise ValueError("NUL characters are not allowed")
    return value


Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    AfterValidator(reject_null_character),
]
Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000),
    AfterValidator(reject_null_character),
]
UserId = Annotated[int, Field(ge=1, le=2_147_483_647)]
UtcDatetime = Annotated[datetime, AfterValidator(lambda value: value.astimezone(UTC))]
T = TypeVar("T")


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, to_lower=True, min_length=3, max_length=50,
            pattern=r"^[A-Za-z0-9_.-]+$",
        ),
    ]
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    description: Description
    priority: Priority = Priority.MEDIUM
    assignee_id: UserId | None = None
    deadline: date


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    description: Description | None = None
    priority: Priority | None = None
    assignee_id: UserId | None = None
    deadline: date | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be supplied")
        for field in self.model_fields_set - {"assignee_id"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    status: Status
    priority: Priority
    author_id: int
    assignee_id: int | None
    deadline: date
    created_at: UtcDatetime
    updated_at: UtcDatetime


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000),
        AfterValidator(reject_null_character),
    ]


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    author_id: int
    text: str
    created_at: UtcDatetime


class Pagination(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2_147_483_647)


class Page(BaseModel, Generic[T]):
    total: int
    limit: int
    offset: int
    items: list[T]


class Sort(StrEnum):
    DEFAULT = "default"
    CREATED_AT = "created_at"
    DEADLINE = "deadline"
    PRIORITY = "priority"


class Direction(StrEnum):
    ASC = "asc"
    DESC = "desc"


class TaskFilters(Pagination):
    model_config = ConfigDict(extra="forbid")

    search: Title | None = None
    status: Status | None = None
    priority: Priority | None = None
    assignee_id: UserId | None = None
    deadline: date | None = None
    deadline_from: date | None = None
    deadline_to: date | None = None
    sort_by: Sort = Sort.DEFAULT
    direction: Direction = Direction.ASC

    @model_validator(mode="after")
    def validate_deadline_range(self) -> Self:
        if self.deadline_from and self.deadline_to and self.deadline_from > self.deadline_to:
            raise ValueError("deadline_from must be on or before deadline_to")
        return self


class Statistics(BaseModel):
    total: int
    by_status: dict[Status, int]
    by_priority: dict[Priority, int]
    overdue: int
    active: int
