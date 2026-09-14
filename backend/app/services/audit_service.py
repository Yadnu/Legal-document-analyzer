"""Audit log service.

Thin wrapper around ``audit_repo.append`` with a stable, typed interface so
callers never have to import the repo directly.

Canonical action strings
------------------------
  document.upload      — browser upload confirmed and ingestion enqueued
  qa.ask               — user sent a Q&A question
  obligation.resolved  — obligation marked as resolved
  document.deleted     — document deleted (Phase 10E)

Any string is accepted; prefer dot-separated <resource>.<verb> for consistency.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import audit_repo


async def log(
    session: AsyncSession,
    tenant_id: str,
    user_id: str,
    action: str,
    *,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Append one audit event row.

    Does not commit — the caller's existing transaction covers it.
    Silently suppresses errors so a logging failure never breaks a request.
    """
    try:
        await audit_repo.append(
            session,
            tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata,
        )
    except Exception:
        # Audit failure must never break the primary request.
        import structlog

        structlog.get_logger(__name__).error(
            "audit_log_failed",
            action=action,
            tenant_id=tenant_id,
        )
