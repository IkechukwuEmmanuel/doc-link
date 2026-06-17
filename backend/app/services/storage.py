"""S3-compatible object storage (MinIO in local dev). Phase 3.

Files are proxied through the backend: bytes are put here after cap checks and
streamed back out only once a file is marked clean.
"""

from __future__ import annotations

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings

settings = get_settings()

_session = aioboto3.Session()
_client_config = Config(signature_version="s3v4", s3={"addressing_style": "path"})


def _client():
    return _session.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=_client_config,
    )


async def ensure_bucket() -> None:
    async with _client() as s3:
        try:
            await s3.head_bucket(Bucket=settings.s3_bucket)
        except ClientError:
            await s3.create_bucket(Bucket=settings.s3_bucket)


async def put_object(key: str, data: bytes, content_type: str) -> None:
    async with _client() as s3:
        await s3.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )


async def get_object(key: str) -> bytes:
    async with _client() as s3:
        resp = await s3.get_object(Bucket=settings.s3_bucket, Key=key)
        async with resp["Body"] as stream:
            return await stream.read()


async def delete_object(key: str) -> None:
    async with _client() as s3:
        await s3.delete_object(Bucket=settings.s3_bucket, Key=key)
