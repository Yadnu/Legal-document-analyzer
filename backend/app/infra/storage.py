"""S3 document storage helpers.

Provides a single async function to download raw document bytes from S3.
All other S3 interactions (presigned URLs) remain in the upload service.
"""

from __future__ import annotations

import structlog
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.exceptions import AwsError
from app.infra.aws import get_s3_client

log = structlog.get_logger(__name__)


async def download_document(s3_key: str) -> bytes:
    """Download raw file bytes from S3.

    Raises ``AwsError`` on any boto3 ``ClientError``; never leaks the full
    s3_key in logs (only the last 16 characters are recorded).
    """
    try:
        async with get_s3_client() as s3:
            response = await s3.get_object(
                Bucket=settings.s3_bucket_name,
                Key=s3_key,
            )
            body = await response["Body"].read()
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "unknown")
        log.error(
            "s3_download_failed",
            s3_key_suffix=s3_key[-16:],
            error_code=error_code,
        )
        raise AwsError("Failed to download document from storage.") from exc

    log.info("s3_download_ok", s3_key_suffix=s3_key[-16:], size_bytes=len(body))
    return body
