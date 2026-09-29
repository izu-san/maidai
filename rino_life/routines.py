"""Event-history-only daily routine aggregation; no inferred state is written."""
from __future__ import annotations
import os
from typing import Any, Callable

class RoutineManager:
    def __init__(self, dsn: str | None = None, connect: Callable[..., Any] | None = None):
        self.dsn = dsn or os.environ.get("RINO_LIFE_DATABASE_URL", "postgresql://rino_life:rino_life@127.0.0.1:54329/rino_life")
        if connect is None:
            import psycopg; connect = psycopg.connect
        self.connect = connect
    def rebuild(self) -> None:
        with self.connect(self.dsn) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM routine_stats")
            cursor.execute("INSERT INTO routine_stats (routine_date,event_type,event_count,last_occurred_at) SELECT (occurred_at AT TIME ZONE 'Asia/Tokyo')::date,type,count(*),max(occurred_at) FROM life_events WHERE type LIKE 'life.%' GROUP BY 1,2")
