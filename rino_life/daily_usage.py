"""Daily PER_DAY consumable deduction, driven through the normal event path."""
from __future__ import annotations
import asyncio, logging
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from .consumables import ConsumableService, today_jst
from .contracts import LifeEventEnvelope

LOG = logging.getLogger(__name__)
SUBJECT = "life.consumable.daily_consumed.v1"

def daily_envelope(day) -> LifeEventEnvelope:
    # A date-derived id makes repeated ticks for the same day a no-op in ConsumableService.apply.
    return LifeEventEnvelope(id=uuid5(NAMESPACE_URL, f"rino-life:{SUBJECT}:{day.isoformat()}"), type=SUBJECT, occurred_at=datetime.now(timezone.utc), source="life-service", actor=None, confidence=1.0, payload={"date": day.isoformat()})

def apply_daily_usage(service: ConsumableService) -> int:
    return len(service.apply(SUBJECT, daily_envelope(today_jst())))

async def run_daily_usage(service: ConsumableService | None = None, interval_seconds: float = 900) -> None:
    service = service or ConsumableService()
    while True:
        try:
            updated = await asyncio.to_thread(apply_daily_usage, service)
            if updated: LOG.info("daily consumable usage applied", extra={"items": updated})
        except asyncio.CancelledError: raise
        except Exception as error:
            LOG.warning("daily consumable usage failed; retrying", extra={"error": str(error)})
        await asyncio.sleep(interval_seconds)
