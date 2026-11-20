import asyncio
import logging

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .domain import Status, today_utc
from .models import Task
from .task_service import overdue_conditions

logger = logging.getLogger(__name__)


async def cancel_overdue(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        result = await session.execute(
            update(Task)
            .where(*overdue_conditions(today_utc()))
            .values(status=Status.CANCELLED, updated_at=func.now())
        )
        await session.commit()
        return result.rowcount


async def sweep_overdue(sessions: async_sessionmaker[AsyncSession], interval: int) -> None:
    while True:
        try:
            changed = await cancel_overdue(sessions)
            if changed:
                logger.info("Cancelled %s overdue tasks", changed)
        except Exception:
            logger.exception("Could not cancel overdue tasks")
        await asyncio.sleep(interval)
