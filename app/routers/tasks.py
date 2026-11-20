from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy import func, select

from .. import task_service as service
from ..db import DbSession
from ..models import Comment, Task
from ..schemas import (
    CommentCreate,
    CommentRead,
    Page,
    Pagination,
    Statistics,
    StatusUpdate,
    TaskCreate,
    TaskFilters,
    TaskRead,
    TaskUpdate,
)
from ..security import CurrentUser, current_user

router = APIRouter(prefix="/tasks", tags=["Tasks"], dependencies=[Depends(current_user)])
TaskId = Annotated[int, Path(ge=1, le=2_147_483_647)]
Filters = Annotated[TaskFilters, Query()]


@router.post("", status_code=201, response_model=TaskRead)
async def create(data: TaskCreate, session: DbSession, user: CurrentUser) -> Task:
    return await service.create_task(session, user, data)


@router.get("", response_model=Page[TaskRead])
async def list_all(session: DbSession, filters: Filters) -> Page[TaskRead]:
    return await service.list_tasks(session, filters)


@router.get("/overdue", response_model=Page[TaskRead])
async def list_overdue(session: DbSession, filters: Filters) -> Page[TaskRead]:
    return await service.list_tasks(session, filters, overdue_only=True)


@router.get("/stats", response_model=Statistics)
async def statistics(session: DbSession) -> Statistics:
    return await service.task_statistics(session)


@router.get("/{task_id}", response_model=TaskRead)
async def retrieve(task_id: TaskId, session: DbSession) -> Task:
    return await service.find_task(session, task_id)


@router.patch("/{task_id}", response_model=TaskRead)
async def edit(task_id: TaskId, data: TaskUpdate, session: DbSession, user: CurrentUser) -> Task:
    task = await service.find_task(session, task_id, lock=True)
    service.require_author(task, user)
    return await service.edit_task(session, task, data)


@router.patch("/{task_id}/status", response_model=TaskRead)
async def set_status(
    task_id: TaskId, data: StatusUpdate, session: DbSession, user: CurrentUser
) -> Task:
    task = await service.find_task(session, task_id, lock=True)
    if user.id not in (task.author_id, task.assignee_id):
        raise HTTPException(status_code=403, detail="Only the author or assignee can change the status")
    return await service.change_status(session, task, data.status)


@router.delete("/{task_id}", status_code=204)
async def remove(task_id: TaskId, session: DbSession, user: CurrentUser) -> Response:
    task = await service.find_task(session, task_id, lock=True)
    service.require_author(task, user)
    await service.delete_task(session, task)
    return Response(status_code=204)


@router.post("/{task_id}/comments", status_code=201, response_model=CommentRead)
async def add_comment(
    task_id: TaskId, data: CommentCreate, session: DbSession, user: CurrentUser
) -> Comment:
    await service.find_task(session, task_id, lock=True)
    comment = Comment(task_id=task_id, author_id=user.id, text=data.text)
    session.add(comment)
    await session.commit()
    return comment


@router.get("/{task_id}/comments", response_model=Page[CommentRead])
async def list_comments(
    task_id: TaskId, session: DbSession, page: Annotated[Pagination, Query()]
) -> Page[CommentRead]:
    await service.find_task(session, task_id)
    total = await session.scalar(select(func.count(Comment.id)).where(Comment.task_id == task_id))
    comments = await session.scalars(
        select(Comment).where(Comment.task_id == task_id)
        .order_by(Comment.created_at, Comment.id).offset(page.offset).limit(page.limit)
    )
    return Page[CommentRead](
        total=total, limit=page.limit, offset=page.offset,
        items=[CommentRead.model_validate(comment) for comment in comments],
    )
