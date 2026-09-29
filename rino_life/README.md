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

### Daily (`PER_DAY`) consumption

A consumable whose `usage_model` is `{"type": "PER_DAY", "amount": N}` is deducted N per day. The Life API lifespan runs `rino_life.daily_usage.run_daily_usage`, which every 15 minutes applies `life.consumable.daily_consumed.v1` (payload `{"date": "YYYY-MM-DD"}`, Japan date) through `ConsumableService.apply`. Each item stores `usage_applied_on` (migration `20260929_09`); the event deducts `N × days since that date`, so missed days are caught up and repeated ticks are idempotent (the event id is derived from the date). Registration starts counting from the registration day, and deducted values are marked `estimated`. `PER_EVENT` (laundry) remains user-reported; items without a usage model change only by adjustment, opening, or purchase.

## Agent integration

`rino_agent/config/mcp.yaml` enables the private `rino-life` stdio MCP by default. Its fixed consumable, laundry, and household-finance tools call the loopback Life API (`RINO_LIFE_API_URL`, default `http://127.0.0.1:54330`) and cannot access PostgreSQL or NATS directly. `Start-MaidAI.ps1` starts the Life API before the Agent in `chat` and `full` profiles. This connection enables user-requested life records and queries only. PC monitor and notification-router outputs are still recorded/routed inside Rino Life and are not automatically delivered to the chat UI.

## Household finance ledger

Rino Life can record approved, manually stated Japanese-yen expenses and income.
It stores a transaction date, standard category, amount, and optional short memo;
it does not connect to banks, cards, or payment accounts, manage balances, import
CSV files, or perform currency conversion. `life.record_finance_transaction`,
`life.correct_finance_transaction`, and `life.cancel_finance_transaction` always
require Agent approval. `life.get_monthly_finance_summary` and
`life.list_finance_transactions` are read-only tools for a `YYYY-MM` month.
Corrections and cancellations retain the original event and transaction history.

## Phase 4 PC / Vision / routine

`PCMonitor` samples disk capacity, CPU usage, and memory usage every 60 seconds by default. It emits threshold alerts only after two consecutive breached samples (a 120-second debounce): `pc.storage_low.v1`, `pc.cpu_high.v1`, and `pc.memory_high.v1`. The remaining PC contracts are `pc.started.v1`, `pc.service_failed.v1`, and `pc.hardware_error.v1`; `PCStateStore` writes idempotent history and current state. `PCMonitor` also watches Windows services (`RINO_PC_WATCH_SERVICES`, default `EventLog,Winmgmt,Dnscache,Dhcp,LanmanWorkstation`; a service stopped for two consecutive samples emits `pc.service_failed.v1`) and polls the System log with a fixed `wevtutil` query for new Critical/Error events from disk/storage/WHEA/GPU providers (`pc.hardware_error.v1`, code `Provider:EventID`; history before the monitor starts is not replayed). It publishes `pc.started.v1` at startup, and the Life API lifespan runs it (`run_pc_monitor`, path `RINO_PC_MONITOR_PATH`, default the system drive), so no separate producer is needed. Vision publishes only `vision.observation_detected.v1` candidates, whose schema requires `confirmation_required: true`; they remain pending and cannot initiate actions or state transitions. `RoutineManager.rebuild()` derives daily counts solely from `life_events`. Hardware errors are priority 4 and bypass quiet hours; other alerts do not.

## Phase 3 notifications

The normal hub starts the notification router with the Life API. Low-stock candidates are written in the same transaction as the consumable snapshot and are routed by the durable `life-notification-router-v1` consumer. Each decision (sent, aggregated, cooldown/quiet-hours suppression, acknowledgement, and resolution) is retained in `notification_history.reason`; the router's notifier (`rino_life/agent_notifier.py`) queues consumable-low and PC (`pc.storage_low.v1`, `pc.cpu_high.v1`, `pc.memory_high.v1`; routed by the durable `life-notification-pc-v1` consumer on `RINO_DEVICE`, priority 3/2/2, so CPU/memory alerts are suppressed during quiet hours) messages in the Agent Service inbox (`POST /internal/notifications`, loopback + Bearer `RINO_AGENT_API_TOKEN`, optional loopback-only `RINO_AGENT_URL`); the SillyTavern RinoAgent extension drains the inbox and shows them in the Rino chat. Delivery failures are logged and not retried (the cooldown still applies). It never triggers Agent execution. `pc.service_failed.v1` and `pc.hardware_error.v1` are delivered as well (priority 3 and 4; hardware errors bypass quiet hours). SwitchBot alerts are delivered too (durable `life-notification-switchbot-v1`, deliver-new): `SwitchBotMonitor` (`rino_life/switchbot_monitor.py`, hosted by the Life API lifespan, read-only, every `RINO_SWITCHBOT_POLL_SECONDS` = 300 s by default, minimum 60) publishes `switchbot.temperature_changed` / `humidity_changed` / `co2_changed` for the `environment` device and `device_state_changed` (lock state, with `unlocked_minutes` / `open_minutes`) for `entrance`; events carry registry keys, never real device IDs. The router (`evaluate_switchbot`) alerts on CO2 >= 1500 ppm, humidity <= 30 % or >= 70 % (priority 2, quiet at night), temperature >= 30 C or <= 10 C, unlocked or open >= 30 min, and a jammed lock (priority 3, so quiet hours do not suppress them). An in-range reading resolves the alert so it can fire again after the 12 h cooldown. Voice output is not handled by Life: the extension adds notifications as ordinary character messages, so reading aloud depends on SillyTavern's TTS settings (not verified).
