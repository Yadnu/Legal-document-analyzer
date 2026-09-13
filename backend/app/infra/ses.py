"""SES email sender for deadline reminders.

In production (SES_ENABLED=true) this calls Amazon SES via boto3.
In development / CI (SES_ENABLED=false, the default) it logs the email
instead of sending it so no real emails are ever fired during tests.

Usage::

    await send_reminder_email(
        to_address="alice@example.com",
        obligation=obligation_row,
        document_title="Service Agreement",
    )
"""

from __future__ import annotations

import structlog

from app.core.config import settings
from app.models.obligation import Obligation

log = structlog.get_logger(__name__)


async def send_reminder_email(
    *,
    to_address: str,
    obligation: Obligation,
    document_title: str,
) -> None:
    """Send (or log) one deadline reminder email.

    Parameters
    ----------
    to_address:
        Clerk user email resolved by the caller.
    obligation:
        The obligation row whose deadline is approaching.
    document_title:
        Human-readable document name for the email body.
    """
    deadline_str = (
        obligation.deadline.strftime("%Y-%m-%d") if obligation.deadline else "unknown"
    )
    subject = f"[Legal Navigator] Reminder: obligation due {deadline_str}"
    body = (
        f'You have an upcoming obligation in "{document_title}".\n\n'
        f"Description: {obligation.description}\n"
        f"Type:        {obligation.obligation_type or 'N/A'}\n"
        f"Deadline:    {deadline_str}\n\n"
        "Log in to Legal Document Navigator to review and resolve this obligation.\n\n"
        "This is a system notification. Do not reply to this email.\n"
        "Legal Document Navigator — understand your documents, not legal advice."
    )

    if not settings.ses_enabled:
        # Dev / CI: log instead of sending so no real emails are fired.
        log.info(
            "ses_reminder_stub",
            to=to_address,
            subject=subject,
            obligation_id=str(obligation.id),
            deadline=deadline_str,
        )
        return

    # Production path — real SES send.
    import aioboto3
    from botocore.exceptions import BotoCoreError, ClientError

    from app.infra.aws import _client_kwargs  # type: ignore[attr-defined]

    session = aioboto3.Session()
    try:
        async with session.client("ses", **_client_kwargs()) as ses:  # type: ignore[attr-defined]
            await ses.send_email(
                Source=settings.ses_from_address,
                Destination={"ToAddresses": [to_address]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                },
            )
        log.info(
            "ses_reminder_sent",
            to=to_address,
            obligation_id=str(obligation.id),
            deadline=deadline_str,
        )
    except (ClientError, BotoCoreError) as exc:
        # Log but don't raise — a failed email should not crash the scheduler.
        log.error(
            "ses_send_failed",
            to=to_address,
            obligation_id=str(obligation.id),
            error=str(exc),
        )
