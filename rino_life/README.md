# Rino Life

## Phase 1 SwitchBot observations

`SwitchBotNatsBridge` transfers only versioned SwitchBot observations from the local Event Bus to JetStream. It preserves IDs, reconnects via the NATS client, and never subscribes to NATS, so it cannot form a loop. `EnvironmentStateStore` atomically writes a processed-event marker, history, and newest per-device snapshot. SwitchBot MCP commands remain on the existing Policy / Approval / Audit path.

1. Copy `infra/.env.life.example` to `infra/.env.life` and replace both passwords with different random values.
2. Start the infrastructure with `./Start-MaidAI.ps1 -Profile docker` (or `docker compose --env-file infra/.env.life -f infra/compose.life.yaml up -d`).
3. Set `RINO_LIFE_DATABASE_URL` to `postgresql+psycopg://<user>:<password>@127.0.0.1:<port>/<database>` and run `python -m alembic upgrade head`.
4. Set `RINO_LIFE_NATS_URL` to `nats://<user>:<password>@127.0.0.1:<port>` and run `python -m rino_life.nats_setup`.

The last two commands are idempotent. `python tools/verify_life_phase0.py assert-ready` confirms the three streams and durable pull consumer. Do not use the example credentials outside a disposable local verification.

## Phase 2 consumables

Run `python -m alembic upgrade head`, then seed the two MVP items:

```powershell
py -3.13 -c "from rino_life.consumables import ConsumableService; ConsumableService().seed()"
```

Start the API with `py -3.13 -m uvicorn rino_life.api:app --host 127.0.0.1 --port 54330` and the publisher with `py -3.13 -m rino_life.outbox`. `POST /events` is the only state-write boundary: it validates the event and writes history, snapshot, and Outbox row in one transaction. The LLM-facing `LifeTools` facade has no database or NATS handle.

## Agent integration

`rino_agent/config/mcp.yaml` enables the private `rino-life` stdio MCP by default. Its fixed consumable and laundry tools call the loopback Life API (`RINO_LIFE_API_URL`, default `http://127.0.0.1:54330`) and cannot access PostgreSQL or NATS directly. `Start-MaidAI.ps1` starts the Life API before the Agent in `chat` and `full` profiles; migrate and seed the database first. This connection enables user-requested life records and queries only. PC monitor and notification-router outputs are still recorded/routed inside Rino Life and are not automatically delivered to the chat UI.

## Phase 4 PC / Vision / routine

`PCMonitor` samples disk capacity, CPU usage, and memory usage every 60 seconds by default. It emits threshold alerts only after two consecutive breached samples (a 120-second debounce): `pc.storage_low.v1`, `pc.cpu_high.v1`, and `pc.memory_high.v1`. The remaining PC contracts are `pc.started.v1`, `pc.service_failed.v1`, and `pc.hardware_error.v1`; `PCStateStore` writes idempotent history and current state. Vision publishes only `vision.observation_detected.v1` candidates, whose schema requires `confirmation_required: true`; they remain pending and cannot initiate actions or state transitions. `RoutineManager.rebuild()` derives daily counts solely from `life_events`. Hardware errors are priority 4 and bypass quiet hours; other alerts do not.

## Phase 3 notifications

Run `py -3.13 -m alembic upgrade head`, then start `py -3.13 -m rino_life.notifications`. Low-stock candidates are written in the same transaction as the consumable snapshot and are routed by the durable `life-notification-router-v1` consumer. Each decision (sent, aggregated, cooldown/quiet-hours suppression, acknowledgement, and resolution) is retained in `notification_history.reason`; notification delivery itself remains an injected adapter, rather than direct Agent execution.
