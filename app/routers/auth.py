from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..db import DbSession
from ..models import User
from ..schemas import Page, Pagination, Registration, Token, UserRead
from ..security import DUMMY_HASH, CurrentUser, current_user, invalid_credentials, issue_token, passwords

router = APIRouter(tags=["Users and authentication"])


@router.post("/auth/register", status_code=201, response_model=UserRead)
async def register(data: Registration, session: DbSession) -> User:
    password_hash = await run_in_threadpool(passwords.hash, data.password)
    user = User(username=data.username, password_hash=password_hash)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        if getattr(error.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(status_code=409, detail="Username is already registered") from error
    return user


@router.post("/auth/login", response_model=Token)
async def login(
    request: Request, form: Annotated[OAuth2PasswordRequestForm, Depends()], session: DbSession
) -> Token:
    username = form.username.strip().lower()
    if len(form.password) > 128 or len(username) > 50:
        raise invalid_credentials()
    user = await session.scalar(select(User).where(User.username == username))
    candidate_hash = user.password_hash if user else DUMMY_HASH
    valid = await run_in_threadpool(passwords.verify, form.password, candidate_hash)
    if user is None or not valid:
        raise invalid_credentials()
    return Token(access_token=issue_token(user.id, request.app.state.settings))


@router.get("/users/me", response_model=UserRead)
async def me(user: CurrentUser) -> User:
    return user


@router.get("/users", dependencies=[Depends(current_user)], response_model=Page[UserRead])
async def list_users(session: DbSession, page: Annotated[Pagination, Query()]) -> Page[UserRead]:
    total = await session.scalar(select(func.count(User.id)))
    users = await session.scalars(select(User).order_by(User.id).offset(page.offset).limit(page.limit))
    return Page[UserRead](
        total=total, limit=page.limit, offset=page.offset,
        items=[UserRead.model_validate(user) for user in users],
    )
