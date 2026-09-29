from datetime import datetime, timezone
from uuid import uuid4
import asyncio
import pytest
from jsonschema import ValidationError
from rino_life.consumables import Consumable, ConsumableService, load_seed
from rino_life.contracts import validate_event
from rino_life.outbox import OutboxPublisher
from rino_life.tools import LifeTools

def envelope(kind, payload): return {"id":str(uuid4()),"type":kind,"occurred_at":datetime.now(timezone.utc).isoformat(),"source":"test","confidence":1.0,"payload":payload}
def item(stock=0): return Consumable("laundry_detergent","洗濯洗剤","household","ml",900,900,stock,False,{"event":"laundry.completed","amount":25},{"remaining_below":150})

def test_seed_contains_two_mvp_items(): assert {"laundry_detergent","fabric_softener"} <= {x["id"] for x in load_seed()}
@pytest.mark.parametrize("kind,payload", [("life.laundry.completed.v1",{"count":1}),("life.consumable.purchased.v1",{"item_id":"laundry_detergent","quantity":2}),("life.consumable.opened.v1",{"item_id":"laundry_detergent"}),("life.consumable.adjusted.v1",{"item_id":"laundry_detergent","remaining":300,"estimated":True}),("life.consumable.registered.v1",{"item_id":"toothpaste","name":"歯磨き粉","category":"household","unit":"g","capacity":120}),("life.consumable.deactivated.v1",{"item_id":"toothpaste"})])
def test_phase2_contracts_validate(kind,payload): assert validate_event(kind,envelope(kind,payload)).type == kind
def test_invalid_adjustment_rejected():
    with pytest.raises(ValidationError): validate_event("life.consumable.adjusted.v1",envelope("life.consumable.adjusted.v1",{"item_id":"x","remaining":-1,"estimated":True}))
def test_state_transition_rules_cover_mvp_cases():
    service=ConsumableService(connect=lambda _:None); detergent=item(); softener=Consumable("fabric_softener","柔軟剤","household","ml",600,600,0,False,{"event":"laundry.completed","amount":20},{"remaining_below":100})
    class Cursor:
        def execute(self,*_): pass
        def fetchall(self): return [detergent,softener]
    cursor=Cursor(); service._row=lambda row:row; service._locked=lambda *_:detergent
    changed=service._targets(cursor,validate_event("life.laundry.completed.v1",envelope("life.laundry.completed.v1",{"count":2})))
    assert {after.id:after.remaining for _,after in changed}=={"laundry_detergent":850,"fabric_softener":560}
    assert service._targets(cursor,validate_event("life.consumable.purchased.v1",envelope("life.consumable.purchased.v1",{"item_id":detergent.id,"quantity":2})))[0][1].stock_unopened==2
    service._locked=lambda *_:item(stock=1)
    assert service._targets(cursor,validate_event("life.consumable.opened.v1",envelope("life.consumable.opened.v1",{"item_id":detergent.id})))[0][1].remaining==900
    service._locked=lambda *_:detergent
    adjusted=service._targets(cursor,validate_event("life.consumable.adjusted.v1",envelope("life.consumable.adjusted.v1",{"item_id":detergent.id,"remaining":300,"estimated":True})))[0][1]
    assert (adjusted.remaining,adjusted.estimated)==(300,True)
def test_open_requires_stock():
    service=ConsumableService(connect=lambda _:None); service._locked=lambda *_:item()
    with pytest.raises(ValueError,match="no unopened stock"): service._targets(None,validate_event("life.consumable.opened.v1",envelope("life.consumable.opened.v1",{"item_id":"laundry_detergent"})))
def test_llm_tools_have_no_db_or_nats_escape_hatch():
    tools=LifeTools(ConsumableService(connect=lambda _:None))
    assert not hasattr(tools,"connect") and not hasattr(tools,"publish")
def test_outbox_ack_marks_row_published():
    class Cursor:
        def __init__(self): self.calls=[]
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def execute(self,sql,values=None): self.calls.append((sql,values))
        def fetchall(self): return [(uuid4(),"life.laundry.completed.v1",{"id":"e"},0)]
    class Conn:
        def __init__(self): self.value=Cursor()
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def cursor(self): return self.value
    conn=Conn(); publisher=OutboxPublisher(connect=lambda _:conn)
    class JS:
        async def publish(self,*_): return object()
    assert asyncio.run(publisher.publish_once(JS()))==1
    assert any("published_at=CURRENT_TIMESTAMP" in sql for sql,_ in conn.value.calls)
def test_outbox_publish_failure_is_retained_for_retry():
    class Cursor:
        def __init__(self): self.calls=[]
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def execute(self,sql,values=None): self.calls.append((sql,values))
        def fetchall(self): return [(uuid4(),"life.laundry.completed.v1",{},0)]
    class Conn:
        def __init__(self): self.value=Cursor()
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def cursor(self): return self.value
    conn=Conn(); publisher=OutboxPublisher(connect=lambda _:conn)
    class BrokenJS:
        async def publish(self,*_): raise RuntimeError("NATS unavailable")
    assert asyncio.run(publisher.publish_once(BrokenJS()))==0
    assert any("last_error" in sql and "published_at=CURRENT_TIMESTAMP" not in sql for sql,_ in conn.value.calls)
