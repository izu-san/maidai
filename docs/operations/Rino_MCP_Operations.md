# Rino MCP Operations

All MCP servers are private stdio child processes owned by Rino Agent Service.
Do not expose them over HTTP or add arbitrary-command tools.

Enable an optional server only by changing its `enabled` entry in
`rino_agent/config/mcp.yaml`. The Service rejects any enabled server that is
not `trust: internal` and `transport: stdio`.

- OBS: set `RINO_OBS_HOST`, `RINO_OBS_PORT`, and `RINO_OBS_PASSWORD`; it uses
  OBS WebSocket rather than GUI automation.
- ComfyUI: set `RINO_COMFYUI_URL` and optionally
  `RINO_COMFYUI_WORKFLOW_DIR`; it uses the ComfyUI HTTP API.
- Windows: set `RINO_WINDOWS_ALLOWED_APPS` to a JSON name-to-absolute-path
  map and `RINO_WINDOWS_ALLOWED_ROOTS` to semicolon-separated roots. No shell,
  PowerShell, cmd, registry, mouse, or keyboard tool is available.
- Rino Life: it is enabled by default and calls only `RINO_LIFE_API_URL`
  (default `http://127.0.0.1:54330`). Its stdio child receives no database,
  NATS, or Agent API credentials. Named consumable/laundry/household-finance tools are exposed;
  it does not accept arbitrary event subjects or payloads.

Household-finance writes (record, correction, cancellation) are `MEDIUM` risk
and always need session approval. Finance reads are read-only. The tools record
manual Japanese-yen ledger facts only; they cannot access bank, card, account,
or payment credentials.

New tool names require a matching entry in `policy.yaml`; otherwise the MAF
Policy Middleware blocks them before invocation.
