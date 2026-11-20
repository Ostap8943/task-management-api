import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .config import Settings
from .routers import auth, tasks
from .worker import sweep_overdue


def create_app(settings: Settings | None = None, *, start_worker: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        config = settings if settings is not None else Settings()
        engine = create_async_engine(config.database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        application.state.settings = config
        application.state.sessions = sessions
        worker = None
        if start_worker:
            worker = asyncio.create_task(sweep_overdue(sessions, config.overdue_check_seconds))
        try:
            yield
        finally:
            if worker is not None:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
            await engine.dispose()

    application = FastAPI(title="Task Management API", version="1.0.0", lifespan=lifespan)
    application.include_router(auth.router)
    application.include_router(tasks.router)
    return application


app = create_app()
