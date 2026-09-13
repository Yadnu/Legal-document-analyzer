"""Deadline reminder service.

Finds obligations whose reminder window has opened, resolves the assignee's
email from the users table, sends the reminder email, and stamps
reminder_sent_at to prevent duplicate sends.

This service is called by the scheduler (app/worker/scheduler.py) on a
configurable interval.  It can also be called directly from tests.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.infra import ses
from app.models.user import User
from app.repositories import obligation_repo
from app.repositories.document_repo import get_by_id as get_document

log = structlog.get_logger(__name__)


async def send_due_reminders(
    session: AsyncSession,
    tenant_id: str,
) -> int:
    """Send reminder emails for all due obligations in this tenant.

    Returns the number of reminders sent (or logged in dev).

    An obligation is "due" when:
      - deadline is set
      - deadline - reminder_days_before <= now  (reminder window opened)
      - deadline > now                          (deadline hasn't passed yet)
      - reminder_sent_at is NULL                (not already sent)
      - is_resolved is False
    """
    due = await obligation_repo.list_due_for_reminder(session, tenant_id)
    if not due:
        log.debug("reminder_none_due", tenant_id=tenant_id)
        return 0

    sent_count = 0
    for obligation in due:
        # ── Resolve recipient email ───────────────────────────────────────────
        to_address = await _resolve_email(session, tenant_id, obligation.assigned_to)
        if to_address is None:
            log.warning(
                "reminder_no_recipient",
                obligation_id=str(obligation.id),
                assigned_to=obligation.assigned_to,
            )
            continue

        # ── Resolve document title for a human-readable email ─────────────────
        doc = await get_document(session, tenant_id, obligation.document_id)
        document_title = doc.title if doc else str(obligation.document_id)

        # ── Send (or log in dev) ──────────────────────────────────────────────
        await ses.send_reminder_email(
            to_address=to_address,
            obligation=obligation,
            document_title=document_title,
        )

        # ── Stamp to prevent duplicate sends ─────────────────────────────────
        await obligation_repo.stamp_reminder_sent(session, obligation)
        sent_count += 1

    if sent_count:
        await session.commit()
        log.info("reminder_batch_done", tenant_id=tenant_id, sent=sent_count)

    return sent_count


async def send_due_reminders_all_tenants(session: AsyncSession) -> int:
    """Run reminder checks across every active tenant in one session.

    The scheduler calls this version so we make one DB round-trip per tenant
    rather than one connection per obligation.
    """
    from sqlalchemy import text

    # Gather distinct tenant IDs that have unresolved obligations with deadlines.
    result = await session.execute(
        text(
            "SELECT DISTINCT tenant_id FROM obligations "
            "WHERE deadline IS NOT NULL AND is_resolved = false "
            "AND reminder_sent_at IS NULL"
        )
    )
    tenant_ids: list[str] = [row[0] for row in result.fetchall()]

    total = 0
    for tenant_id in tenant_ids:
        # Set the per-connection RLS variable so policies apply correctly.
        from app.db.rls import set_tenant_context

        await set_tenant_context(session, tenant_id)
        count = await send_due_reminders(session, tenant_id)
        total += count

    return total


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _resolve_email(
    session: AsyncSession,
    tenant_id: str,
    clerk_user_id: str | None,
) -> str | None:
    """Look up the email for a Clerk user_id within this tenant."""
    if not clerk_user_id:
        return None
    result = await session.execute(
        select(User).where(
            col(User.tenant_id) == tenant_id,
            col(User.clerk_user_id) == clerk_user_id,
            col(User.is_active).is_(True),
        )
    )
    user = result.scalar_one_or_none()
    return user.email if user else None
