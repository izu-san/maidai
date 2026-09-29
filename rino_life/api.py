"""Loopback Life API: the only HTTP write boundary for life state."""
from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from .consumables import ConsumableService
from .contracts import LifeEventEnvelope
from .phase5 import Phase5Service

app = FastAPI(title="Rino Life API", docs_url=None, redoc_url=None)
service = ConsumableService()
phase5_service = Phase5Service()

class EventInput(BaseModel):
    type: str = Field(pattern=r"^life\.(laundry\.completed|consumable\.(purchased|opened|adjusted|registered|deactivated)|maintenance\.completed|trash\.collected|package\.updated|subscription\.updated)\.v1$")
    payload: dict
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: str = Field(default="manual", min_length=1, max_length=64)
    actor: str | None = None
    correlation_id: str | None = None

def as_dict(item):
    return {"id":item.id,"name":item.name,"category":item.category,"unit":item.unit,"capacity":item.capacity,"remaining":item.remaining,"stock_unopened":item.stock_unopened,"estimated":item.estimated,"version":item.version}

@app.get("/health")
def health(): return {"status":"ok", "bind":"loopback-only"}

@app.get("/consumables")
def list_consumables():
    # A dedicated listing query is deliberately kept out of the LLM write path.
    return {"items": [as_dict(item) for item in service.list_active()]}

@app.get("/consumables/low")
def list_low_stock_consumables():
    return {"items": [as_dict(item) for item in service.list_low_stock()]}

@app.get("/consumables/{item_id}")
def get_consumable(item_id: str):
    item = service.get(item_id)
    if not item: raise HTTPException(404, "Unknown consumable")
    return as_dict(item)

@app.post("/events")
def emit_event(request: EventInput):
    envelope = LifeEventEnvelope(id=uuid4(), type=request.type, occurred_at=datetime.now(timezone.utc), source=request.source, actor=request.actor, confidence=request.confidence, correlation_id=request.correlation_id, payload=request.payload)
    try:
        if envelope.type.startswith(("life.maintenance.", "life.trash.", "life.package.", "life.subscription.")):
            return {"event_id": str(envelope.id), "updated": phase5_service.apply(envelope.type, envelope)}
        items = service.apply(envelope.type, envelope)
    except (ValueError, KeyError) as error: raise HTTPException(422, str(error)) from error
    return {"event_id": str(envelope.id), "updated": [as_dict(item) for item in items]}
