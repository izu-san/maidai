# Rino Agent Service API

The service binds only to `127.0.0.1:8766`. Every endpoint except `GET /health`
requires `Authorization: Bearer <RINO_AGENT_API_TOKEN>`.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/agent/run` | Start or continue a user-request session. |
| POST | `/agent/approve` | Consume one pending approval and resume the session. |
| POST | `/agent/reject` | Consume one pending approval and resume it as rejected. |
| POST | `/agent/respond` | Bind an explicit natural-language approval or rejection to one pending approval. |
| POST | `/agent/cancel` | Cancel a session and invalidate all its approvals. |
| GET | `/agent/session/{id}` | Read the current in-memory session state. |
| GET | `/agent/tools` | List the MCP tools allowlisted by the Service. |
| POST | `/events` | Submit a bounded, authenticated local event. |
| GET/POST | `/agent/tasks` | List or register notification-only event waiters. |
| POST | `/workflows/sleep` | Run the deterministic low-risk sleep workflow. |
| GET | `/workflows/checkpoints` | List MAF checkpoint IDs; never resumes automatically. |
| GET | `/health` | Loopback liveness probe; no sensitive data. |

`/agent/run` accepts `{ "goal": "...", "session_id": "optional" }`. It returns
either `succeeded` or `approval_required`. Approval requests are scoped to the
session and tool arguments, expire after 60 seconds, and are single use.

Sessions and approvals are intentionally in-memory. On a Service restart they
are discarded, so an action can never resume automatically. MAF workflow
checkpoints are stored in the ACL-restricted checkpoint directory. Registered
event waiters are stored separately with an HMAC integrity check; they are
notification-only and never resume an external action.

The bundled `Rino Agent` SillyTavern extension accepts supported Japanese
home and life requests directly in the chat, for example `電気を消して` or
`洗濯終わったよ`. It intercepts only explicit matching requests; ordinary
conversation remains on the normal chat path. `/rino <goal>` remains available
as an explicit alternative. The extension calls SillyTavern's local
`/api/rino-agent` proxy, which holds the Agent token server-side and forwards
only `/agent/run` and natural approval responses to the loopback Agent Service.
It has no direct SwitchBot or MCP access. High-risk requests still require the
Agent's normal confirmation.

Before first launch, run `./Initialize-RinoAgent.ps1`. It creates a random
local token in `rino_agent/.env`, applies a user-and-SYSTEM-only ACL, and never
prints the token. Start-MaidAI passes it only to the local SillyTavern server
proxy; it is not stored in browser extension settings.

Existing Vision integrations can dispatch `rino-agent-event` with a `detail`
object matching `{ type, source, timestamp, data }`; the extension forwards it
to the authenticated Event Gateway. It never forwards a vision event directly
to the LLM. Event timestamps must contain a timezone and event/task data is
limited to 16 KiB.
