"""AWS client factories.

All configuration is read from ``app.core.config.settings``.  The
``aws_endpoint_url`` override makes LocalStack transparent in development:
when the variable is empty the factory omits the keyword argument entirely,
so the standard AWS SDK endpoint resolution applies in production.

Usage
-----
::

    async with get_s3_client() as s3:
        url = await s3.generate_presigned_url(...)

    async with get_sqs_client() as sqs:
        await sqs.send_message(...)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3

from app.core.config import settings

_session = aioboto3.Session()


def _client_kwargs() -> dict:
    """Build the keyword arguments shared by every boto3 client call."""
    kwargs: dict = {
        "region_name": settings.aws_default_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
    }
    # Only pass endpoint_url when explicitly configured (e.g. LocalStack).
    # An empty string would override the SDK's own endpoint resolution.
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return kwargs


@asynccontextmanager
async def get_s3_client() -> AsyncIterator[Any]:
    """Async context manager that yields an aioboto3 S3 client.

    Example::

        async with get_s3_client() as s3:
            url = await s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": settings.s3_bucket_name, "Key": key},
                ExpiresIn=settings.presigned_url_expires_seconds,
            )
    """
    # aioboto3 stubs type client() as `_`; ignore keeps pyright happy.
    async with _session.client("s3", **_client_kwargs()) as client:  # type: ignore
        yield client


@asynccontextmanager
async def get_sqs_client() -> AsyncIterator[Any]:
    """Async context manager that yields an aioboto3 SQS client.

    Example::

        async with get_sqs_client() as sqs:
            await sqs.send_message(
                QueueUrl=settings.sqs_queue_url,
                MessageBody=json.dumps(payload),
            )
    """
    async with _session.client("sqs", **_client_kwargs()) as client:  # type: ignore
        yield client
