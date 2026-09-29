# Rino Life

Rino Life の初期化には `requirements-rino-agent.txt` の Python 依存関係が必要です。未導入の環境では先に `py -3.13 -m pip install -r requirements-rino-agent.txt` を実行してください。

## Phase 1 SwitchBot observations

`SwitchBotNatsBridge` transfers only versioned SwitchBot observations from the local Event Bus to JetStream. It preserves IDs, reconnects via the NATS client, and never subscribes to NATS, so it cannot form a loop. `EnvironmentStateStore` atomically writes a processed-event marker, history, and newest per-device snapshot. SwitchBot MCP commands remain on the existing Policy / Approval / Audit path.

1. Copy `infra/.env.life.example` to `infra/.env.life` and replace both passwords with different random values.
2. Run `./Start-MaidAI.ps1` for the normal chat profile. It starts Compose with health checks, derives the private connection URLs from `infra/.env.life`, then idempotently runs migration, seed, and JetStream setup before starting the Life API and Agent.
3. Use `./Start-MaidAI.ps1 -Profile docker` when only PostgreSQL / NATS are needed. In that case run `./Initialize-RinoLife.ps1` from the same PowerShell session before starting Life Python processes manually.

`Initialize-RinoLife.ps1` is idempotent and URI-escapes credentials when it derives `RINO_LIFE_DATABASE_URL` and `RINO_LIFE_NATS_URL`; explicit values remain supported as overrides. `python tools/verify_life_phase0.py assert-ready` confirms the three streams and durable pull consumer. Do not use the example credentials outside a disposable local verification.

## Phase 2 consumables

The normal hub profile runs migration and seeds the two MVP items automatically. For a manual setup, run `./Initialize-RinoLife.ps1` first.

```powershell
py -3.13 -c "from rino_life.consumables import ConsumableService; ConsumableService().seed()"
```

Start the API with `py -3.13 -m uvicorn rino_life.api:app --host 127.0.0.1 --port 54330`. Its lifespan owns the outbox publisher and the notification, environment, PC-state, and Vision consumers. `POST /events` is the only state-write boundary: it validates the event and writes history, snapshot, and Outbox row in one transaction. The LLM-facing `LifeTools` facade has no database or NATS handle.

## Agent integration

`rino_agent/config/mcp.yaml` enables the private `rino-life` stdio MCP by default. Its fixed consumable and laundry tools call the loopback Life API (`RINO_LIFE_API_URL`, default `http://127.0.0.1:54330`) and cannot access PostgreSQL or NATS directly. `Start-MaidAI.ps1` starts the Life API before the Agent in `chat` and `full` profiles. This connection enables user-requested life records and queries only. PC monitor and notification-router outputs are still recorded/routed inside Rino Life and are not automatically delivered to the chat UI.

## Phase 4 PC / Vision / routine

`PCMonitor` samples disk capacity, CPU usage, and memory usage every 60 seconds by default. It emits threshold alerts only after two consecutive breached samples (a 120-second debounce): `pc.storage_low.v1`, `pc.cpu_high.v1`, and `pc.memory_high.v1`. The remaining PC contracts are `pc.started.v1`, `pc.service_failed.v1`, and `pc.hardware_error.v1`; `PCStateStore` writes idempotent history and current state. Vision publishes only `vision.observation_detected.v1` candidates, whose schema requires `confirmation_required: true`; they remain pending and cannot initiate actions or state transitions. `RoutineManager.rebuild()` derives daily counts solely from `life_events`. Hardware errors are priority 4 and bypass quiet hours; other alerts do not.

## Phase 3 notifications

The normal hub starts the notification router with the Life API. Low-stock candidates are written in the same transaction as the consumable snapshot and are routed by the durable `life-notification-router-v1` consumer. Each decision (sent, aggregated, cooldown/quiet-hours suppression, acknowledgement, and resolution) is retained in `notification_history.reason`; notification delivery itself remains an injected adapter, rather than direct Agent execution.
