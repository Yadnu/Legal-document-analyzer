"""APScheduler-based deadline reminder scheduler.

Runs inside the same process as the SQS worker (worker/main.py).
Uses APScheduler's AsyncIOScheduler so it shares the event loop and
never blocks the SQS polling coroutine.

The scheduler fires one job every ``reminder_check_interval_minutes`` minutes
(default: 60).  The job opens a fresh DB session, runs
``reminder_service.send_due_reminders_all_tenants``, and closes the session.

Usage::

    from app.worker.scheduler import build_scheduler

    scheduler = build_scheduler(async_session_factory)
    scheduler.start()
    ...
    scheduler.shutdown()
"""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings

log = structlog.get_logger(__name__)


def build_scheduler(
    session_factory: async_sessionmaker,  # type: ignore[type-arg]
) -> AsyncIOScheduler:
    """Create and configure an AsyncIOScheduler with the reminder job.

    The caller is responsible for calling ``scheduler.start()`` and
    ``scheduler.shutdown(wait=False)`` around the worker loop.
    """
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        _run_reminders,
        trigger="interval",
        minutes=settings.reminder_check_interval_minutes,
        args=[session_factory],
        id="deadline_reminders",
        name="Deadline reminder check",
        # Fire once right away on start so we don't wait a full interval after
        # a worker restart (next_run_time=None means fire immediately).
        next_run_time=None,  # APScheduler will fire at the first interval tick
        max_instances=1,  # never overlap — if a run is slow, skip the next tick
        coalesce=True,  # collapse missed ticks into one run
    )

    return scheduler


async def _run_reminders(
    session_factory: async_sessionmaker,  # type: ignore[type-arg]
) -> None:
    """Job callback: open a session and dispatch reminder emails."""
    log.info("reminder_job_start")
    try:
        from app.services.reminder_service import send_due_reminders_all_tenants

        async with session_factory() as session:
            sent = await send_due_reminders_all_tenants(session)
        log.info("reminder_job_done", sent=sent)
    except Exception as exc:
        # Log but don't raise — a scheduler job should never crash the worker.
        log.error("reminder_job_failed", error=str(exc), exc_info=True)
