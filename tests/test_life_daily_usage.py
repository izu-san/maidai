from datetime import date, timedelta
import pytest
from jsonschema import ValidationError
from rino_life.consumables import Consumable, ConsumableService, today_jst
from rino_life.contracts import validate_event
from rino_life.daily_usage import SUBJECT, daily_envelope

def food(remaining=900.0): return Consumable("cat_food", "猫のご飯", "pet", "g", 2000, remaining, 0, False, {"type": "PER_DAY", "amount": 50}, {"remaining_below": 300})

class Cursor:
    def __init__(self, rows): self.rows, self.calls = rows, []
    def execute(self, sql, values=None): self.calls.append((sql, values))
    def fetchall(self): return self.rows

def targets(applied_on, through, item=None):
    item = item or food(); service = ConsumableService(connect=lambda _: None); service._row = lambda row: item
    cursor = Cursor([(*range(11), applied_on)])
    return service._daily_targets(cursor, through), cursor

def test_daily_event_contract():
    assert validate_event(SUBJECT, daily_envelope(date(2026, 9, 30))).payload == {"date": "2026-09-30"}
    with pytest.raises(ValidationError): validate_event(SUBJECT, {**daily_envelope(date(2026, 9, 30)).model_dump(), "payload": {"date": "tomorrow"}})

def test_daily_envelope_id_is_stable_per_day():
    assert daily_envelope(date(2026, 9, 30)).id == daily_envelope(date(2026, 9, 30)).id != daily_envelope(date(2026, 10, 1)).id

def test_one_day_deducts_one_amount():
    today = today_jst(); changed, cursor = targets(today - timedelta(days=1), today)
    assert [(a.remaining, a.estimated) for _, a in changed] == [(850.0, True)]
    assert any("usage_applied_on" in sql and values[0] == today for sql, values in cursor.calls if values)

def test_missed_days_are_caught_up():
    today = today_jst(); changed, _ = targets(today - timedelta(days=4), today)
    assert changed[0][1].remaining == 700.0

def test_same_day_is_idempotent():
    today = today_jst(); changed, cursor = targets(today, today)
    assert changed == [] and not any(values for sql, values in cursor.calls if "UPDATE" in sql)

def test_remaining_never_goes_negative():
    today = today_jst(); changed, _ = targets(today - timedelta(days=10), today, food(120.0))
    assert changed[0][1].remaining == 0.0

def test_legacy_item_without_applied_date_only_starts_counting():
    today = today_jst(); changed, cursor = targets(None, today)
    assert changed == [] and any("UPDATE" in sql for sql, _ in cursor.calls)

def test_future_date_rejected():
    with pytest.raises(ValueError, match="future"): targets(None, today_jst() + timedelta(days=2))

def test_register_per_day_starts_today_and_validates_amount():
    calls = []
    class C:
        def execute(self, sql, values): calls.append(values)
    event = daily_envelope(today_jst()).model_copy(update={"type": "life.consumable.registered.v1", "payload": {"item_id": "cat_food", "name": "猫のご飯", "category": "pet", "unit": "g", "capacity": 2000, "remaining": 900, "usage_model": {"type": "PER_DAY", "amount": 50}}})
    ConsumableService._register(C(), event)
    assert calls[0][-1] == today_jst()
    bad = event.model_copy(update={"payload": {**event.payload, "usage_model": {"type": "PER_DAY", "amount": 0}}})
    with pytest.raises(ValueError, match="positive"): ConsumableService._register(C(), bad)
