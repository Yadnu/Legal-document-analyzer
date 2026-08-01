"""Async SQS long-polling ingestion worker.

Entry-point: ``python -m worker.main``

The worker loops forever, pulling up to 10 messages at a time from the main
ingestion queue (long-poll, 20-second wait).  On success the message is
deleted from the queue.  On failure the message is NOT deleted so SQS retries
it up to ``maxReceiveCount`` times before moving it to the DLQ.

Status flow: processing -> ready | failed

Phase 4 stub: actual parsing/chunking/embedding is replaced by a 1-second
sleep so the full infrastructure path (DB, SQS, status transitions) can be
validated before the heavy pipeline is wired in.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import structlog
from botocore.exceptions import ClientError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.rls import set_tenant_context
from app.infra.aws import get_sqs_client
from app.models.document import DocumentStatus
from app.repositories import document_repo

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# DB setup — separate engine from the API process
# ---------------------------------------------------------------------------

_engine = create_async_engine(settings.database_url, echo=False)
_AsyncSession = async_sessionmaker(_engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Message processing
# ---------------------------------------------------------------------------


async def process_message(body: dict, session: AsyncSession) -> None:
    """Process one ingestion message.

    1. Parse fields from the SQS message body.
    2. Open a tenant-scoped DB session (RLS context set).
    3. Fetch document; skip if already ``ready`` (idempotent re-delivery).
    4. [Phase 4 stub] Simulate ingestion work.
    5. Transition status to ``ready`` on success or ``failed`` on error.

    Raises on failure so the caller does NOT delete the message, letting SQS
    retry and eventually route to the DLQ.
    """
    raw_doc_id: str = body["document_id"]
    tenant_id: str = body["tenant_id"]
    doc_id = uuid.UUID(raw_doc_id)

    bound_log = log.bind(document_id=raw_doc_id, tenant_id=tenant_id)

    await set_tenant_context(session, tenant_id)

    doc = await document_repo.get_by_id(session, tenant_id, doc_id)
    if doc is None:
        bound_log.warning("worker_document_not_found")
        return  # nothing to do; message can be safely deleted

    if doc.status == DocumentStatus.READY:
        bound_log.info("worker_skipped_already_ready")
        return  # idempotent: already processed, delete the message

    bound_log.info("worker_processing_start", status=doc.status)

    try:
        # ── Phase 4 stub ─────────────────────────────────────────────────
        # Replace this block with real parse/chunk/embed logic in Phase 4.
        bound_log.info("ingestion_stub", document_id=raw_doc_id, tenant_id=tenant_id)
        await asyncio.sleep(1)
        # ── End stub ─────────────────────────────────────────────────────

        await document_repo.set_status(session, tenant_id, doc_id, DocumentStatus.READY)
        await session.commit()
        bound_log.info("worker_processing_done", status=DocumentStatus.READY)

    except Exception as exc:
        # Roll back any partial writes, then record the failure reason.
        await session.rollback()
        error_reason = str(exc)
        bound_log.error("worker_processing_failed", error=error_reason)
        try:
            await document_repo.set_status(
                session,
                tenant_id,
                doc_id,
                DocumentStatus.FAILED,
                error_reason=error_reason,
            )
            await session.commit()
        except Exception:
            bound_log.exception("worker_failed_to_record_failure")
        raise  # re-raise so the message is NOT deleted → SQS retries → DLQ


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------


async def _poll_once(sqs) -> None:  # type: ignore[no-untyped-def]
    """Receive up to 10 messages and process them sequentially."""
    try:
        response = await sqs.receive_message(
            QueueUrl=settings.sqs_queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
        )
    except ClientError as exc:
        log.error("sqs_receive_failed", error=str(exc))
        await asyncio.sleep(5)  # back-off before retrying
        return

    messages = response.get("Messages", [])
    if not messages:
        return

    for msg in messages:
        receipt = msg["ReceiptHandle"]
        try:
            body = json.loads(msg["Body"])
        except (json.JSONDecodeError, KeyError) as exc:
            log.error("sqs_message_parse_error", error=str(exc), body=msg.get("Body"))
            # Poison message — delete it so it doesn't block the queue.
            await _delete_message(sqs, receipt)
            continue

        try:
            async with _AsyncSession() as session:
                await process_message(body, session)
            # Success — safe to delete.
            await _delete_message(sqs, receipt)
        except Exception:
            # process_message already logged the error. Do NOT delete so SQS
            # can retry and eventually route to the DLQ.
            pass


async def _delete_message(sqs, receipt: str) -> None:  # type: ignore[no-untyped-def]
    """Best-effort message deletion; log but do not raise on failure."""
    try:
        await sqs.delete_message(
            QueueUrl=settings.sqs_queue_url,
            ReceiptHandle=receipt,
        )
    except ClientError as exc:
        log.error("sqs_delete_failed", error=str(exc))


async def run() -> None:
    """Start the long-polling worker loop.

    Runs indefinitely until the process is killed (SIGTERM / Ctrl-C).
    """
    configure_logging()
    log.info("worker_starting", queue_url=settings.sqs_queue_url)

    if not settings.sqs_queue_url:
        log.error("worker_no_queue_url_configured")
        raise RuntimeError("SQS_QUEUE_URL is not configured — cannot start worker.")

    async with get_sqs_client() as sqs:
        while True:
            await _poll_once(sqs)


if __name__ == "__main__":
    asyncio.run(run())
