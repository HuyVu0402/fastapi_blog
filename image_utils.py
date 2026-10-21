import logging
import uuid
from io import BytesIO
from pathlib import Path

import boto3
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image, ImageOps
from starlette.concurrency import run_in_threadpool

from config import settings

PROFILE_PICS_DIR = Path("media/profile_pics")
logger = logging.getLogger(__name__)
STORAGE_ERRORS = (BotoCoreError, ClientError, S3UploadFailedError, OSError)


def _get_s3_client():
    return boto3.client(
        "s3",
        region_name=settings.s3_region,
        aws_access_key_id=(
            settings.s3_access_key_id.get_secret_value()
            if settings.s3_access_key_id
            else None
        ),
        aws_secret_access_key=(
            settings.s3_secret_access_key.get_secret_value()
            if settings.s3_secret_access_key
            else None
        ),
        endpoint_url=settings.s3_endpoint_url,
    )


def process_profile_image(content: bytes) -> tuple[bytes, str]:
    with Image.open(BytesIO(content)) as original:
        img = ImageOps.exif_transpose(original)

        img = ImageOps.fit(img, (300, 300), method=Image.Resampling.LANCZOS)

        if img.mode != "RGB":
            img = img.convert("RGB")

        filename = f"{uuid.uuid4().hex}.jpg"

        output = BytesIO()
        img.save(output, "JPEG", quality=85, optimize=True)
        output.seek(0)

    return output.read(), filename


def _upload_to_s3(file_bytes: bytes, key: str) -> None:
    s3 = _get_s3_client()
    s3.upload_fileobj(
        BytesIO(file_bytes),
        settings.s3_bucket_name,
        key,
        ExtraArgs={"ContentType": "image/jpeg"},
    )


def _delete_from_s3(key: str) -> None:
    s3 = _get_s3_client()
    s3.delete_object(Bucket=settings.s3_bucket_name, Key=key)


async def upload_profile_image(file_bytes: bytes, filename: str) -> None:
    if Path(filename).name != filename:
        raise ValueError("Invalid profile picture filename")
    if not settings.s3_bucket_name:
        await run_in_threadpool(_save_local, file_bytes, filename)
        return
    key = f"profile_pics/{filename}"
    await run_in_threadpool(_upload_to_s3, file_bytes, key)


async def delete_profile_image(filename: str | None) -> None:
    if not filename or Path(filename).name != filename:
        return
    if not settings.s3_bucket_name:
        await run_in_threadpool((PROFILE_PICS_DIR / filename).unlink, missing_ok=True)
        return
    key = f"profile_pics/{filename}"
    await run_in_threadpool(_delete_from_s3, key)


def _save_local(file_bytes: bytes, filename: str) -> None:
    PROFILE_PICS_DIR.mkdir(parents=True, exist_ok=True)
    (PROFILE_PICS_DIR / filename).write_bytes(file_bytes)


async def cleanup_profile_image(filename: str | None) -> None:
    """Cleanup must not turn an already committed account change into a failure."""
    try:
        await delete_profile_image(filename)
    except STORAGE_ERRORS:
        logger.warning("Profile picture cleanup failed for %s; manual cleanup may be required", filename)
