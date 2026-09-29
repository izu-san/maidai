"""Transactional household-ledger domain service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json, os
from typing import Any, Callable
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from .contracts import LifeEventEnvelope, validate_event

FINANCE_EVENTS = {
    "life.finance.transaction_recorded.v1", "life.finance.transaction_corrected.v1",
    "life.finance.transaction_cancelled.v1",
}
EXPENSE_CATEGORIES = {"食費", "日用品", "住居", "光熱", "通信", "交通", "医療", "保険", "被服", "娯楽", "教育", "定期購入", "贈答", "特別支出", "その他"}
INCOME_CATEGORIES = {"給与", "賞与", "副収入", "返金", "贈与", "その他"}

@dataclass(frozen=True)
class FinanceTransaction:
    id: UUID; kind: str; amount_yen: int; category: str; occurred_on: date; note: str | None; status: str; version: int
    def snapshot(self) -> dict[str, Any]:
        return {"id": str(self.id), "kind": self.kind, "amount_yen": self.amount_yen, "category": self.category,
                "occurred_on": self.occurred_on.isoformat(), "note": self.note, "status": self.status, "version": self.version}

class FinanceService:
    def __init__(self, dsn: str | None = None, connect: Callable[..., Any] | None = None):
        self.dsn = dsn or os.environ.get("RINO_LIFE_DATABASE_URL", "postgresql://rino_life:rino_life@127.0.0.1:54329/rino_life")
        if connect is None:
            def connect(*args: Any, **kwargs: Any) -> Any:
                import psycopg
                return psycopg.connect(*args, **kwargs)
        self.connect = connect

    def apply(self, subject: str, event: dict[str, Any] | LifeEventEnvelope) -> dict[str, Any]:
        envelope = validate_event(subject, event)
        if envelope.type not in FINANCE_EVENTS: raise ValueError(f"Unsupported finance event: {envelope.type}")
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM life_events WHERE id=%s", (envelope.id,))
            if cursor.fetchone(): return {"idempotent": True}
            cursor.execute("INSERT INTO life_events (id,type,occurred_at,source,actor,confidence,correlation_id,causation_id,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)", (envelope.id,envelope.type,envelope.occurred_at,envelope.source,envelope.actor,envelope.confidence,envelope.correlation_id,envelope.causation_id,json.dumps(envelope.payload)))
            if subject == "life.finance.transaction_recorded.v1":
                transaction = self._from_payload(envelope.id, envelope.payload)
                cursor.execute("INSERT INTO finance_transactions (id,kind,amount_yen,category,occurred_on,note,status,version) VALUES (%s,%s,%s,%s,%s,%s,'active',1)", (transaction.id,transaction.kind,transaction.amount_yen,transaction.category,transaction.occurred_on,transaction.note))
                before = None; after = transaction.snapshot()
            else:
                transaction = self._locked(cursor, UUID(envelope.payload["transaction_id"]))
                before = transaction.snapshot()
                if subject == "life.finance.transaction_corrected.v1":
                    if transaction.status != "active": raise ValueError("Cancelled transactions cannot be corrected")
                    after_transaction = self._from_payload(transaction.id, envelope.payload, version=transaction.version + 1)
                    cursor.execute("UPDATE finance_transactions SET kind=%s,amount_yen=%s,category=%s,occurred_on=%s,note=%s,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=%s", (after_transaction.kind,after_transaction.amount_yen,after_transaction.category,after_transaction.occurred_on,after_transaction.note,transaction.id))
                else:
                    if transaction.status != "active": raise ValueError("Transaction is already cancelled")
                    after_transaction = FinanceTransaction(transaction.id, transaction.kind, transaction.amount_yen, transaction.category, transaction.occurred_on, transaction.note, "cancelled", transaction.version + 1)
                    cursor.execute("UPDATE finance_transactions SET status='cancelled',version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=%s", (transaction.id,))
                after = after_transaction.snapshot()
            cursor.execute("INSERT INTO finance_transaction_history (id,transaction_id,event_id,before,after,reason) VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s)", (uuid4(), UUID(after["id"]), envelope.id, json.dumps(before), json.dumps(after), envelope.type))
            cursor.execute("INSERT INTO outbox_events (id,subject,payload) VALUES (%s,%s,%s::jsonb)", (uuid4(), subject, json.dumps(envelope.model_dump(mode="json"))))
            return after

    def monthly_summary(self, month: str) -> dict[str, Any]:
        start, end = self._month_bounds(month)
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT kind,COALESCE(SUM(amount_yen),0) FROM finance_transactions WHERE status='active' AND occurred_on >= %s AND occurred_on < %s GROUP BY kind", (start,end))
            totals = dict(cursor.fetchall())
            cursor.execute("SELECT kind,category,SUM(amount_yen) FROM finance_transactions WHERE status='active' AND occurred_on >= %s AND occurred_on < %s GROUP BY kind,category ORDER BY kind,category", (start,end))
            categories = [{"kind": kind, "category": category, "amount_yen": int(amount)} for kind,category,amount in cursor.fetchall()]
        income, expense = int(totals.get("income", 0)), int(totals.get("expense", 0))
        return {"month": month, "income_yen": income, "expense_yen": expense, "balance_yen": income-expense, "categories": categories}

    def list_month(self, month: str, limit: int = 100) -> list[dict[str, Any]]:
        start, end = self._month_bounds(month)
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id,kind,amount_yen,category,occurred_on,note,status,version FROM finance_transactions WHERE occurred_on >= %s AND occurred_on < %s ORDER BY occurred_on DESC, updated_at DESC LIMIT %s", (start,end,limit))
            return [self._row(row).snapshot() for row in cursor.fetchall()]

    @staticmethod
    def _month_bounds(month: str) -> tuple[date, date]:
        try: start = date.fromisoformat(f"{month}-01")
        except ValueError as error: raise ValueError("month must be YYYY-MM") from error
        return start, date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
    @staticmethod
    def _from_payload(transaction_id: UUID, payload: dict[str, Any], version: int = 1) -> FinanceTransaction:
        allowed = EXPENSE_CATEGORIES if payload["kind"] == "expense" else INCOME_CATEGORIES
        if payload["category"] not in allowed: raise ValueError("Unknown finance category for transaction kind")
        occurred_on = date.fromisoformat(payload["occurred_on"])
        if occurred_on > datetime.now(ZoneInfo("Asia/Tokyo")).date(): raise ValueError("Future finance transactions are not supported")
        return FinanceTransaction(transaction_id, payload["kind"], int(payload["amount_yen"]), payload["category"], occurred_on, payload.get("note"), "active", version)
    def _locked(self, cursor: Any, transaction_id: UUID) -> FinanceTransaction:
        cursor.execute("SELECT id,kind,amount_yen,category,occurred_on,note,status,version FROM finance_transactions WHERE id=%s FOR UPDATE", (transaction_id,))
        row = cursor.fetchone()
        if row is None: raise ValueError("Unknown finance transaction")
        return self._row(row)
    @staticmethod
    def _row(row: Any) -> FinanceTransaction:
        values = list(row); values[2] = int(values[2]); return FinanceTransaction(*values)
