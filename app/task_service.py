from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .domain import (
    ACTIVE_STATUSES,
    ACTIVE_TASK_LIMIT,
    LOCKED_ASSIGNEE_STATUSES,
    TRANSITIONS,
    Priority,
    Status,
    today_utc,
)
from .models import Task, User
from .schemas import Direction, Page, Sort, Statistics, TaskCreate, TaskFilters, TaskRead, TaskUpdate

PRIORITY_ORDER = case(
    {Priority.HIGH.value: 1, Priority.MEDIUM.value: 2, Priority.LOW.value: 3},
    value=Task.priority,
)
SORT_COLUMNS = {
    Sort.CREATED_AT: Task.created_at,
    Sort.DEADLINE: Task.deadline,
    Sort.PRIORITY: PRIORITY_ORDER,
}


def overdue_conditions(today: date) -> tuple:
    return Task.deadline < today, Task.status.in_(ACTIVE_STATUSES)


async def find_task(session: AsyncSession, task_id: int, *, lock: bool = False) -> Task:
    stmt = select(Task).where(Task.id == task_id)
    if lock:
        stmt = stmt.with_for_update()
    task = await session.scalar(stmt)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def require_author(task: Task, user: User) -> None:
    if task.author_id != user.id:
        raise HTTPException(status_code=403, detail="Only the task author can do this")


def validate_deadline(deadline: date) -> None:
    if deadline < today_utc():
        raise HTTPException(status_code=422, detail="Deadline cannot be in the past")


async def check_assignee_capacity(session: AsyncSession, assignee_id: int) -> None:
    # FOR NO KEY UPDATE serializes competing assignments for this user while
    # allowing concurrent foreign-key checks for tasks authored by the user.
    assignee = await session.scalar(
        select(User.id).where(User.id == assignee_id).with_for_update(key_share=True)
    )
    if assignee is None:
        raise HTTPException(status_code=404, detail="Assignee not found")
    active = await session.scalar(
        select(func.count(Task.id)).where(
            Task.assignee_id == assignee_id, Task.status.in_(ACTIVE_STATUSES)
        )
    )
    if active >= ACTIVE_TASK_LIMIT:
        raise HTTPException(status_code=409, detail="Assignee already has 10 active tasks")


async def create_task(session: AsyncSession, author: User, data: TaskCreate) -> Task:
    validate_deadline(data.deadline)
    if data.assignee_id is not None:
        await check_assignee_capacity(session, data.assignee_id)
    task = Task(author_id=author.id, **data.model_dump())
    session.add(task)
    await session.commit()
    return task


async def edit_task(session: AsyncSession, task: Task, data: TaskUpdate) -> Task:
    if task.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Done and cancelled tasks cannot be edited")
    changes = data.model_dump(exclude_unset=True)
    validate_deadline(changes.get("deadline", task.deadline))
    assignee_id = changes.get("assignee_id", task.assignee_id)
    if assignee_id != task.assignee_id:
        if task.status in LOCKED_ASSIGNEE_STATUSES:
            raise HTTPException(status_code=409, detail="The assignee is locked in review")
        if assignee_id is not None:
            await check_assignee_capacity(session, assignee_id)
    for field, value in changes.items():
        setattr(task, field, value)
    task.updated_at = datetime.now(UTC)
    await session.commit()
    return task


async def change_status(session: AsyncSession, task: Task, next_status: Status) -> Task:
    if next_status not in TRANSITIONS[task.status]:
        raise HTTPException(
            status_code=409, detail=f"Cannot move from {task.status.value} to {next_status.value}"
        )
    if next_status == Status.DONE:
        if task.assignee_id is None:
            raise HTTPException(status_code=409, detail="Assign a user before completing a task")
        if task.deadline < today_utc():
            raise HTTPException(status_code=409, detail="An overdue task cannot be completed")

    task.status = next_status
    task.updated_at = datetime.now(UTC)
    await session.commit()
    return task


async def delete_task(session: AsyncSession, task: Task) -> None:
    if task.status in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Only done or cancelled tasks can be deleted")
    await session.delete(task)
    await session.commit()


def apply_filters(filters: TaskFilters) -> list:
    conditions = []
    if filters.search is not None:
        conditions.append(or_(
            Task.title.icontains(filters.search, autoescape=True),
            Task.description.icontains(filters.search, autoescape=True),
        ))
    exact_filters = (
        (Task.status, filters.status),
        (Task.priority, filters.priority),
        (Task.assignee_id, filters.assignee_id),
        (Task.deadline, filters.deadline),
    )
    conditions.extend(column == value for column, value in exact_filters if value is not None)
    if filters.deadline_from is not None:
        conditions.append(Task.deadline >= filters.deadline_from)
    if filters.deadline_to is not None:
        conditions.append(Task.deadline <= filters.deadline_to)
    return conditions


async def list_tasks(
    session: AsyncSession, filters: TaskFilters, *, overdue_only: bool = False
) -> Page[TaskRead]:
    conditions = apply_filters(filters)
    if overdue_only:
        conditions.extend(overdue_conditions(today_utc()))

    if filters.sort_by == Sort.DEFAULT:
        ordering = [PRIORITY_ORDER.asc(), Task.deadline.asc()]
    else:
        column = SORT_COLUMNS[filters.sort_by]
        ordering = [column.desc() if filters.direction == Direction.DESC else column.asc()]
    total = await session.scalar(select(func.count(Task.id)).where(*conditions))
    rows = await session.scalars(
        select(Task).where(*conditions)
        .order_by(*ordering, Task.id.asc()).offset(filters.offset).limit(filters.limit)
    )
    return Page[TaskRead](
        total=total, limit=filters.limit, offset=filters.offset,
        items=[TaskRead.model_validate(task) for task in rows],
    )


async def task_statistics(session: AsyncSession) -> Statistics:
    columns = [
        func.count(Task.id).label("total"),
        func.count(Task.id).filter(*overdue_conditions(today_utc())).label("overdue"),
        func.count(Task.id).filter(Task.status.in_(ACTIVE_STATUSES)).label("active"),
    ]
    columns.extend(
        func.count(Task.id).filter(Task.status == status).label(status.value)
        for status in Status
    )
    columns.extend(
        func.count(Task.id).filter(Task.priority == priority).label(priority.value)
        for priority in Priority
    )
    counts = (await session.execute(select(*columns))).mappings().one()
    return Statistics(
        total=counts["total"],
        overdue=counts["overdue"],
        active=counts["active"],
        by_status={status: counts[status.value] for status in Status},
        by_priority={priority: counts[priority.value] for priority in Priority},
    )
