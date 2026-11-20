import os
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.config import Settings
from app.main import create_app


def upgrade(connection):
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


@pytest.fixture
async def app_factory():
    settings = Settings()
    url = make_url(os.environ.get("TEST_DATABASE_URL", settings.database_url))
    schema = f"test_{uuid4().hex}"
    admin_engine = create_async_engine(url)
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(CreateSchema(schema))

        schema_url = url.update_query_dict({"options": f"-csearch_path={schema}"})
        test_settings = Settings(
            database_url=schema_url.render_as_string(hide_password=False),
            jwt_secret=settings.jwt_secret,
            overdue_check_seconds=1,
        )
        engine = create_async_engine(test_settings.database_url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(upgrade)
        finally:
            await engine.dispose()

        @asynccontextmanager
        async def start(*, worker=False):
            app = create_app(test_settings, start_worker=worker)
            async with app.router.lifespan_context(app):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    yield app, client

        yield start
    finally:
        try:
            async with admin_engine.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        finally:
            await admin_engine.dispose()


@pytest.fixture
async def running_app(app_factory):
    async with app_factory() as running:
        yield running


@pytest.fixture
def client(running_app):
    return running_app[1]
