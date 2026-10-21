from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from botocore.exceptions import ClientError
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import image_utils
from auth import create_access_token, hash_reset_token
from config import settings
from models import PasswordResetToken, Post
from tests.conftest import auth_header, create_test_user, login_user

pytestmark = pytest.mark.anyio


@pytest.fixture
async def account(client):
    user = await create_test_user(client)
    return user, auth_header(await login_user(client))


@pytest.fixture
def picture():
    return (Path(__file__).parent / "test_image.jpg").read_bytes()


async def upload(client, account, picture):
    user, headers = account
    return await client.patch(
        f"/api/users/{user['id']}/picture", headers=headers,
        files={"file": ("avatar.jpg", picture, "image/jpeg")},
    )


async def test_reset_token_is_hashed_and_single_use(client, account, isolate_services, db_session):
    known = await client.post("/api/users/forgot-password", json={"email": "test@example.com"})
    unknown = await client.post("/api/users/forgot-password", json={"email": "unknown@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    isolate_services.assert_awaited_once()
    token = isolate_services.call_args.kwargs["token"]
    stored = (await db_session.execute(select(PasswordResetToken))).scalar_one()
    assert stored.token_hash == hash_reset_token(token) and stored.token_hash != token
    payload = {"token": token, "new_password": "replacement-password"}
    assert (await client.post("/api/users/reset-password", json=payload)).status_code == 200
    assert (await client.post("/api/users/reset-password", json=payload)).status_code == 400
    assert (await client.post("/api/users/token", data={
        "username": "test@example.com", "password": "testpassword123",
    })).status_code == 401
    await login_user(client, password="replacement-password")


async def test_expired_reset_token(client, account, isolate_services, db_session):
    await client.post("/api/users/forgot-password", json={"email": "test@example.com"})
    token = isolate_services.call_args.kwargs["token"]
    stored = (await db_session.execute(select(PasswordResetToken))).scalar_one()
    stored.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()
    response = await client.post("/api/users/reset-password", json={
        "token": token, "new_password": "replacement-password",
    })
    assert response.status_code == 400
    await login_user(client)


async def test_new_reset_and_password_change_invalidate_tokens(client, account, isolate_services):
    await client.post("/api/users/forgot-password", json={"email": "test@example.com"})
    first = isolate_services.call_args.kwargs["token"]
    await client.post("/api/users/forgot-password", json={"email": "test@example.com"})
    second = isolate_services.call_args.kwargs["token"]
    assert (await client.post("/api/users/reset-password", json={
        "token": first, "new_password": "replacement-password",
    })).status_code == 400
    _, headers = account
    response = await client.patch("/api/users/me/password", headers=headers, json={
        "current_password": "wrong-password", "new_password": "replacement-password",
    })
    assert response.status_code == 400
    response = await client.patch("/api/users/me/password", headers=headers, json={
        "current_password": "testpassword123", "new_password": "replacement-password",
    })
    assert response.status_code == 200
    assert (await client.post("/api/users/reset-password", json={
        "token": second, "new_password": "another-password",
    })).status_code == 400
    await login_user(client, password="replacement-password")


@pytest.mark.parametrize("kind", ["expired", "missing_exp", "invalid_subject", "malformed"])
async def test_invalid_access_tokens(client, account, kind):
    user, _ = account
    token = {
        "expired": create_access_token({"sub": str(user["id"])}, timedelta(seconds=-1)),
        "missing_exp": jwt.encode({"sub": str(user["id"])}, settings.secret_key.get_secret_value()),
        "invalid_subject": create_access_token({"sub": "not-a-number"}),
        "malformed": "not.a.jwt",
    }[kind]
    assert (await client.get("/api/users/me", headers=auth_header(token))).status_code == 401


@pytest.mark.parametrize("query", ["skip=-1", "limit=0", "limit=101"])
async def test_pagination_bounds(client, query):
    assert (await client.get(f"/api/posts?{query}")).status_code == 422


async def test_pagination_stable_order_and_author_filter(client, account, db_session):
    user, _ = account
    other = await create_test_user(client, username="other", email="other@example.com")
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    posts = [Post(title=str(i), content="test", user_id=user["id"], date_posted=stamp) for i in range(5)]
    db_session.add_all(posts)
    db_session.add(Post(title="other", content="test", user_id=other["id"], date_posted=stamp))
    await db_session.commit()
    first = (await client.get("/api/posts?limit=3")).json()
    last = (await client.get("/api/posts?skip=3&limit=3")).json()
    ids = [post["id"] for post in first["posts"] + last["posts"]]
    assert ids == sorted(set(ids), reverse=True) and len(ids) == 6
    assert first["has_more"] and not last["has_more"]
    own = (await client.get(f"/api/users/{user['id']}/posts")).json()
    assert own["total"] == 5
    assert all(post["user_id"] == user["id"] for post in own["posts"])


async def test_picture_replacement_and_account_deletion(client, account, picture, mocked_aws):
    first = await upload(client, account, picture)
    assert first.status_code == 200
    second = await upload(client, account, picture)
    assert second.status_code == 200
    filename = second.json()["image_file"]
    objects = mocked_aws.list_objects_v2(Bucket="test-bucket")["Contents"]
    assert [obj["Key"] for obj in objects] == [f"profile_pics/{filename}"]
    obj = mocked_aws.get_object(Bucket="test-bucket", Key=f"profile_pics/{filename}")
    assert obj["ContentType"] == "image/jpeg"
    with Image.open(BytesIO(obj["Body"].read())) as image:
        assert image.size == (300, 300) and image.format == "JPEG"
    user, headers = account
    assert (await client.delete(f"/api/users/{user['id']}", headers=headers)).status_code == 204
    assert mocked_aws.list_objects_v2(Bucket="test-bucket")["KeyCount"] == 0


async def test_invalid_and_oversized_images(client, account, picture, mocked_aws, monkeypatch):
    assert (await upload(client, account, b"invalid image")).status_code == 400
    monkeypatch.setattr(settings, "max_upload_size_bytes", 4)
    assert (await upload(client, account, picture)).status_code == 400
    assert mocked_aws.list_objects_v2(Bucket="test-bucket")["KeyCount"] == 0


async def test_picture_ownership(client, account, picture, mocked_aws):
    other = await create_test_user(client, username="other", email="other@example.com")
    _, headers = account
    response = await upload(client, (other, headers), picture)
    assert response.status_code == 403
    assert (await client.delete(f"/api/users/{other['id']}/picture", headers=headers)).status_code == 403
    assert mocked_aws.list_objects_v2(Bucket="test-bucket")["KeyCount"] == 0


async def test_storage_failure_preserves_current_picture(client, account, picture):
    before = (await upload(client, account, picture)).json()["image_file"]
    error = ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject")
    with patch("routers.users.upload_profile_image", new_callable=AsyncMock, side_effect=error):
        assert (await upload(client, account, picture)).status_code == 500
    assert (await client.get("/api/users/me", headers=account[1])).json()["image_file"] == before


async def test_failed_commit_removes_new_image(client, account, picture, mocked_aws):
    with patch.object(AsyncSession, "commit", new_callable=AsyncMock, side_effect=RuntimeError("commit failed")):
        with pytest.raises(RuntimeError, match="commit failed"):
            await upload(client, account, picture)
    assert mocked_aws.list_objects_v2(Bucket="test-bucket")["KeyCount"] == 0
    assert (await client.get("/api/users/me", headers=account[1])).json()["image_file"] is None


async def test_local_storage_fallback(client, account, picture, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket_name", None)
    monkeypatch.setattr(image_utils, "PROFILE_PICS_DIR", tmp_path)
    response = await upload(client, account, picture)
    assert response.status_code == 200
    filename = response.json()["image_file"]
    assert (tmp_path / filename).is_file()
    assert response.json()["image_path"] == f"/media/profile_pics/{filename}"
    user, headers = account
    assert (await client.delete(f"/api/users/{user['id']}/picture", headers=headers)).status_code == 200
    assert not (tmp_path / filename).exists()


async def test_password_pages(client):
    assert (await client.get("/forgot-password")).status_code == 200
    response = await client.get("/reset-password")
    assert response.status_code == 200
    assert response.headers["referrer-policy"] == "no-referrer"
