from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from .config import Settings
from .db import DbSession
from .models import User

passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash("dummy-password-for-unknown-users")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
ALGORITHM = "HS256"
ISSUER = "task-management-api"


def issue_token(user_id: int, settings: Settings) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iss": ISSUER,
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )


def invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_user(
    request: Request, session: DbSession, token: Annotated[str, Depends(oauth2_scheme)]
) -> User:
    settings: Settings = request.app.state.settings
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["sub", "iss", "iat", "exp"]},
        )
        user_id = int(claims["sub"])
        if not 0 < user_id <= 2_147_483_647:
            raise ValueError("Invalid user ID")
    except (InvalidTokenError, ValueError, TypeError) as error:
        raise invalid_credentials() from error

    user = await session.get(User, user_id)
    if user is None:
        raise invalid_credentials()
    return user


CurrentUser = Annotated[User, Depends(current_user)]
