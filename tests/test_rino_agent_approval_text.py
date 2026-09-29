import pytest
from rino_agent.approval_text import amount, describe_approval
from rino_life.consumables import ConsumableService
from rino_life.daily_usage import daily_envelope
from datetime import date

REGISTER = {"capacity": 2000, "category": "ペット用品", "item_id": "nutro", "name": "ニュートロ ナチュラルチョイス", "remaining": 800, "reminder": {"remaining_below": 500}, "unit": "g", "usage_model": {"amount": 50, "type": "PER_DAY"}}

def test_amount_shows_large_units_alongside():
    assert amount(2000, "g") == "2,000g（2kg）" and amount(800, "g") == "800g" and amount(1450, "ml") == "1,450ml（1.45L）"

def test_register_is_a_natural_sentence_without_raw_data():
    text = describe_approval("life.register_consumable", REGISTER)
    assert text == "ニュートロ ナチュラルチョイス（ペット用品）を管理対象に登録しますね。容量は2,000g（2kg）で、今の残量は800gです。毎日50gずつ自動で減らします（登録した翌日から）。残りが500g以下になったらお知らせします。この内容でよろしいですか？（はい／いいえ）"
    assert not any(token in text for token in ("{", "}", "item_id", "usage_model"))

def test_register_variants():
    manual = describe_approval("life.register_consumable", {"name": "洗剤", "category": "household", "unit": "ml", "capacity": 900, "usage_model": {"type": "PER_EVENT", "event": "laundry.completed", "amount": 25}})
    assert "満タン" in manual and "洗濯が終わったと教えていただくたびに25mlずつ" in manual and "設定しません" in manual
    assert "教えていただいたときだけ" in describe_approval("life.register_consumable", {**REGISTER, "usage_model": {}})

def test_other_tools():
    assert "3,500円" in describe_approval("life.record_finance_transaction", {"kind": "expense", "amount_yen": 3500, "category": "食費", "occurred_on": "2026-09-29", "note": "スーパー"})
    assert "収入" in describe_approval("life.record_finance_transaction", {"kind": "income", "amount_yen": 1, "category": "給与", "occurred_on": "2026-09-29"})
    assert "26度" in describe_approval("home.set_temperature", {"celsius": 26.0})
    assert "施錠" in describe_approval("home.lock_door", {}) and "テレビ" in describe_approval("home.tv_on", {})
    assert "取り消し" in describe_approval("life.cancel_finance_transaction", {"transaction_id": "t1"})

def test_unknown_or_malformed_falls_back_to_none():
    assert describe_approval("obs.start_stream", {}) is None and describe_approval("life.deactivate_consumable", {}) is None

class Cursor:
    def __init__(self): self.calls = []
    def execute(self, sql, values=None): self.calls.append(values)

def event(**overrides):
    payload = {**REGISTER, **overrides}
    return daily_envelope(date(2026, 9, 29)).model_copy(update={"type": "life.consumable.registered.v1", "payload": payload})

@pytest.mark.parametrize("overrides,message", [
    ({"capacity": 2}, "looks like a kg/L value"),
    ({"reminder": {"remaining_below": 3000}}, "remaining_below"),
    ({"usage_model": {"type": "PER_DAY", "amount": 5000}}, "cannot exceed capacity"),
    ({"remaining": 3000}, "remaining cannot exceed capacity"),
])
def test_register_rejects_inconsistent_units(overrides, message):
    with pytest.raises(ValueError, match=message): ConsumableService._register(Cursor(), event(**overrides))

def test_register_accepts_consistent_values():
    cursor = Cursor(); ConsumableService._register(cursor, event()); assert cursor.calls
