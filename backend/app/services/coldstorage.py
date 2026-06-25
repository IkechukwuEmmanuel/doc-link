"""Cold-storage eligibility flagging. Phase 6.

Per PRD §5.4 this is a *storage-cost control*, not deletion and not a user-facing
"expiry": pads untouched for longer than the configured window are flagged
``cold_storage_eligible = True`` so a future tier can relocate their bytes to
cheaper storage. Nothing is destroyed and no "expiring soon" messaging is shown.

Mechanism (the boring option): the core ``flag_cold_pads()`` is a plain async
function. It can be driven two ways, both documented in DECISIONS.md:
  - as a cron entry point: ``python -m app.services.coldstorage``
  - as an in-process daily loop started from the app lifespan (no extra
    dependency — just an asyncio task), convenient for single-node deploys.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.pad import Pad
from app.services import pin as pin_service

logger = logging.getLogger("spacepad.coldstorage")
settings = get_settings()

_ONE_DAY_SECONDS = 24 * 60 * 60
_task: asyncio.Task | None = None


async def flag_cold_pads(now: datetime | None = None) -> int:
    """Flag pads whose ``last_opened_at`` is older than the window. Returns count."""
    reference = now or datetime.now(timezone.utc)
    cutoff = reference - timedelta(days=settings.cold_storage_after_days)
    async with SessionLocal() as db:
        result = await db.execute(
            update(Pad)
            .where(
                Pad.last_opened_at < cutoff,
                Pad.cold_storage_eligible.is_(False),
            )
            .values(cold_storage_eligible=True)
        )
        await db.commit()
        flagged = result.rowcount or 0
    if flagged:
        logger.info("Flagged %d pad(s) as cold-storage eligible", flagged)
    return flagged


async def purge_expired_unlocks(now: datetime | None = None) -> int:
    """Reap expired ``pad_pin_unlocks`` rows. Expiry is enforced on every access
    regardless, so this is housekeeping to keep the table bounded — it rides the
    same daily sweep as cold-storage flagging (see DECISIONS.md). Returns count."""
    async with SessionLocal() as db:
        purged = await pin_service.purge_expired(db, now=now)
    if purged:
        logger.info("Purged %d expired PIN-unlock row(s)", purged)
    return purged


async def _run_loop() -> None:
    while True:
        try:
            await flag_cold_pads()
            await purge_expired_unlocks()
        except Exception:  # never let the loop die on a transient DB error
            logger.exception("cold-storage sweep failed")
        await asyncio.sleep(_ONE_DAY_SECONDS)


def start_scheduler() -> None:
    """Start the in-process daily sweep (no-op if already running)."""
    global _task
    if _task is not None and not _task.done():
        return
    try:
        _task = asyncio.create_task(_run_loop())
    except RuntimeError:
        # No running loop (e.g. invoked outside the app) — cron path will cover it.
        _task = None


def stop_scheduler() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None


async def _sweep_once() -> tuple[int, int]:
    return await flag_cold_pads(), await purge_expired_unlocks()


if __name__ == "__main__":  # cron entry point
    logging.basicConfig(level=logging.INFO)
    flagged, purged = asyncio.run(_sweep_once())
    print(f"cold-storage: flagged {flagged} pad(s); purged {purged} expired unlock(s)")
