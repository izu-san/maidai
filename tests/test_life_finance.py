from datetime import datetime, timezone
from uuid import uuid4

import pytest
from jsonschema import ValidationError

from rino_life.contracts import validate_event
from rino_life.finance import EXPENSE_CATEGORIES, INCOME_CATEGORIES, FinanceService
from rino_life import mcp_server


def envelope(kind, payload):
    return {"id": str(uuid4()), "type": kind, "occurred_at": datetime.now(timezone.utc).isoformat(), "source": "test", "confidence": 1.0, "payload": payload}


def test_finance_contracts_accept_standard_income_and_expense():
    assert validate_event("life.finance.transaction_recorded.v1", envelope("life.finance.transaction_recorded.v1", {"kind":"expense","amount_yen":650,"category":next(iter(EXPENSE_CATEGORIES)),"occurred_on":"2026-09-29"})).type.endswith("recorded.v1")
    assert validate_event("life.finance.transaction_corrected.v1", envelope("life.finance.transaction_corrected.v1", {"transaction_id":str(uuid4()),"kind":"income","amount_yen":1000,"category":next(iter(INCOME_CATEGORIES)),"occurred_on":"2026-09-29"})).type.endswith("corrected.v1")


@pytest.mark.parametrize("payload", [
    {"kind":"expense","amount_yen":0,"category":"other","occurred_on":"2026-09-29"},
    {"kind":"expense","amount_yen":100,"category":"salary","occurred_on":"2026-09-29"},
])
def test_finance_contract_rejects_invalid_amount_or_category(payload):
    with pytest.raises(ValidationError):
        validate_event("life.finance.transaction_recorded.v1", envelope("life.finance.transaction_recorded.v1", payload))


def test_finance_service_rejects_future_transaction_dates():
    with pytest.raises(ValueError, match="Future"):
        FinanceService._from_payload(uuid4(), {"kind":"expense","amount_yen":100,"category":next(iter(EXPENSE_CATEGORIES)),"occurred_on":"2999-01-01"})


def test_finance_mcp_posts_fixed_event_and_validates_month(monkeypatch):
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b'{"event_id":"event-1","updated":{}}'
    def fake_urlopen(request, timeout):
        calls.append((request.full_url, request.get_method()))
        return Response()
    monkeypatch.setattr(mcp_server, "urlopen", fake_urlopen)
    assert mcp_server.record_finance_transaction("expense", 650, next(iter(EXPENSE_CATEGORIES)), "2026-09-29")["event_id"] == "event-1"
    assert calls == [("http://127.0.0.1:54330/events", "POST")]
    with pytest.raises(ValueError, match="YYYY-MM"):
        mcp_server.get_monthly_finance_summary("2026-13")
