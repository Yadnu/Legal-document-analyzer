"""Upload service.

Owns the two-step upload flow:

  1. ``request_upload``  — validate content-type and size, generate a presigned
     S3 PUT URL, persist a ``Document`` row with status ``processing``.

  2. ``confirm_upload``  — enqueue an SQS ingestion job after the browser PUT
     completes and return the document DTO for status polling.

The service layer is the only place that touches AWS or the database for this
feature.  The router injects a DB session and calls these methods; no business
logic lives in the router.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import PurePosixPath

import structlog
from botocore.exceptions import ClientError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AwsError, NotFoundError, ValidationError
from app.infra.aws import get_s3_client, get_sqs_client
from app.models.document import DocumentStatus
from app.repositories import document_repo
from app.repositories.document_repo import DocumentCreateData
from app.schemas.document import DocumentResponse, PresignedUploadResponse

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _idempotency_key(tenant_id: str, filename: str, size_bytes: int) -> str:
    """SHA-256 of (tenant_id + filename + size_bytes) as a hex digest.

    Deterministic: retrying the exact same file for the same tenant always
    yields the same key, preventing duplicate ``Document`` rows.
    """
    raw = tenant_id + filename + str(size_bytes)
    return hashlib.sha256(raw.encode()).hexdigest()


def _derive_title(filename: str) -> str:
    """Use the stem of the filename as a human-readable document title."""
    stem = PurePosixPath(filename).stem
    return stem if stem else filename


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------


class UploadService:
    """Stateless service; a single module-level instance is shared per worker."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def request_upload(
        self,
        *,
        session: AsyncSession,
        tenant_id: str,
        user_id: str,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> PresignedUploadResponse:
        """Validate, (optionally create a Document row), and return a presigned URL.

        Idempotent: calling again with the same (tenant, filename, size) returns
        the existing ``document_id`` and a fresh presigned URL.
        """
        # ── 1. Validate content type ──────────────────────────────────────────
        if content_type not in settings.upload_allowed_content_types:
            raise ValidationError(
                f"Content type '{content_type}' is not allowed. "
                f"Accepted: {settings.upload_allowed_content_types}"
            )

        # ── 2. Validate size ─────────────────────────────────────────────────
        if size_bytes > settings.upload_max_size_bytes:
            max_mb = settings.upload_max_size_bytes // (1024 * 1024)
            raise ValidationError(
                f"File size {size_bytes:,} bytes exceeds the {max_mb} MB limit."
            )

        # ── 3. Derive idempotency key ────────────────────────────────────────
        idem_key = _idempotency_key(tenant_id, filename, size_bytes)

        # ── 4. Idempotency check ─────────────────────────────────────────────
        existing = await document_repo.get_by_idempotency_key(
            session, tenant_id, idem_key
        )
        if existing is not None and existing.status != DocumentStatus.FAILED:
            # Re-issue a fresh presigned URL; do NOT create a duplicate row.
            upload_url = await self._presign(existing.s3_key, content_type, size_bytes)
            log.info(
                "upload_idempotent_reuse",
                document_id=str(existing.id),
                tenant_id=tenant_id,
                status=existing.status,
            )
            return PresignedUploadResponse(
                document_id=existing.id,
                upload_url=upload_url,
                s3_key=existing.s3_key,
                expires_in=settings.presigned_url_expires_seconds,
            )

        # ── 5. Generate S3 key ───────────────────────────────────────────────
        s3_key = f"{tenant_id}/{uuid.uuid4()}/{filename}"

        # ── 6. Generate presigned URL ────────────────────────────────────────
        upload_url = await self._presign(s3_key, content_type, size_bytes)

        # ── 7. Persist Document row ──────────────────────────────────────────
        data = DocumentCreateData(
            title=_derive_title(filename),
            original_filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            s3_key=s3_key,
            idempotency_key=idem_key,
            uploaded_by=user_id,
        )
        doc = await document_repo.create(session, tenant_id, data)
        await session.commit()

        log.info(
            "upload_requested",
            document_id=str(doc.id),
            tenant_id=tenant_id,
            status=doc.status,
        )

        # ── 8. Return DTO ────────────────────────────────────────────────────
        return PresignedUploadResponse(
            document_id=doc.id,
            upload_url=upload_url,
            s3_key=s3_key,
            expires_in=settings.presigned_url_expires_seconds,
        )

    async def confirm_upload(
        self,
        *,
        session: AsyncSession,
        tenant_id: str,
        document_id: uuid.UUID,
    ) -> DocumentResponse:
        """Enqueue the SQS ingestion job and return the current document state.

        Called after the browser has successfully PUT the file to S3.
        """
        # ── 1. Fetch document (tenant-scoped) ────────────────────────────────
        doc = await document_repo.get_by_id(session, tenant_id, document_id)
        if doc is None:
            raise NotFoundError(f"Document {document_id} not found.")

        # ── 2. Publish SQS ingestion message ─────────────────────────────────
        payload = {
            "document_id": str(doc.id),
            "tenant_id": doc.tenant_id,
            "s3_key": doc.s3_key,
            "idempotency_key": doc.idempotency_key,
        }
        try:
            async with get_sqs_client() as sqs:
                await sqs.send_message(
                    QueueUrl=settings.sqs_queue_url,
                    MessageBody=json.dumps(payload),
                )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "unknown")
            log.error(
                "sqs_send_failed",
                document_id=str(doc.id),
                tenant_id=tenant_id,
                error_code=error_code,
            )
            raise AwsError("Failed to enqueue ingestion job. Please retry.") from exc

        log.info(
            "upload_confirmed",
            document_id=str(doc.id),
            tenant_id=tenant_id,
            status=doc.status,
        )

        # ── 3. Return DTO ────────────────────────────────────────────────────
        return DocumentResponse.model_validate(doc)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _presign(self, s3_key: str, content_type: str, size_bytes: int) -> str:
        """Generate a presigned S3 PUT URL with ContentType and ContentLength signed.

        Signing ContentType forces the browser PUT to include the matching
        ``Content-Type`` header; ContentLength pins the exact file size.
        Both conditions are validated server-side before this URL is issued.
        """
        try:
            async with get_s3_client() as s3:
                url: str = await s3.generate_presigned_url(
                    "put_object",
                    Params={
                        "Bucket": settings.s3_bucket_name,
                        "Key": s3_key,
                        "ContentType": content_type,
                        "ContentLength": size_bytes,
                    },
                    ExpiresIn=settings.presigned_url_expires_seconds,
                )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "unknown")
            # Log the suffix of the key only — never the full path.
            log.error(
                "s3_presign_failed",
                s3_key_suffix=s3_key[-16:],
                error_code=error_code,
            )
            raise AwsError("Failed to generate upload URL. Please retry.") from exc
        return url


# Module-level singleton — import and use this directly.
upload_service = UploadService()
