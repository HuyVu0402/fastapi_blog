"""Each test gets an isolated database and mocked external services."""

import os
from unittest.mock import AsyncMock, patch

import boto3
import pytest
from httpx import ASGITransport, AsyncClient
from moto import mock_aws
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_ENV = {
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "SECRET_KEY": "test-only-secret-key-with-at-least-32-characters",
    "S3_BUCKET_NAME": "test-bucket",
    "S3_REGION": "us-east-1",
    "S3_ACCESS_KEY_ID": "testing",
    "S3_SECRET_ACCESS_KEY": "testing",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_EC2_METADATA_DISABLED": "true",
    "MAIL_SERVER": "localhost",
    "MAIL_PORT": "1025",
    "MAIL_USERNAME": "",
    "MAIL_PASSWORD": "",
    "MAIL_FROM": "test@example.com",
    "MAIL_USE_TLS": "false",
    "FRONTEND_URL": "http://test",
    "POSTS_PER_PAGE": "10",
    "MAX_UPLOAD_SIZE_BYTES": "5242880",
}

with patch.dict(os.environ, TEST_ENV):
    from config import settings
    from database import Base, get_db
    from main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def isolate_services(monkeypatch):
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    # Ignore any endpoint/CDN configured in the developer's .env.
    monkeypatch.setattr(settings, "s3_endpoint_url", None)
    monkeypatch.setattr(settings, "s3_public_url", None)
    with patch("routers.users.send_password_reset_email", new_callable=AsyncMock) as mail:
        yield mail


@pytest.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture
def mocked_aws(isolate_services):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        yield s3


@pytest.fixture
async def client(session_factory, mocked_aws):
    async def override_get_db():
        async with session_factory() as session:
            yield session

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


async def create_test_user(
    client: AsyncClient,
    username: str = "testuser",
    email: str = "test@example.com",
    password: str = "testpassword123",
) -> dict:
    response = await client.post(
        "/api/users",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 201, f"Failed to create user: {response.text}"
    return response.json()


async def login_user(
    client: AsyncClient,
    email: str = "test@example.com",
    password: str = "testpassword123",
) -> str:
    response = await client.post(
        "/api/users/token",
        data={
            "username": email,
            "password": password,
        },
    )
    assert response.status_code == 200, f"Failed to login: {response.text}"
    return response.json()["access_token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
