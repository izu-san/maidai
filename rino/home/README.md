# Rino Home Tool

`rino.home` is the safe, provider-independent Home Tool from the integration specification. It currently uses SwitchBot OpenAPI v1.1 through `SwitchBotAdapter`.

## Setup

Set these variables in the process that starts the bridge; never put their values in a character card, prompt, or config file.

```powershell
$env:SWITCHBOT_TOKEN = '...'
$env:SWITCHBOT_SECRET = '...'
$env:SWITCHBOT_CO2_DEVICE_ID = '...'
$env:SWITCHBOT_LIGHT_DEVICE_ID = '...'
$env:SWITCHBOT_AIRCON_DEVICE_ID = '...'
$env:SWITCHBOT_TV_DEVICE_ID = '...'
$env:SWITCHBOT_LOCK_DEVICE_ID = '...'
py -m rino_mcp.switchbot.server
```

When starting through `Start-MaidAI.ps1`, copy `.env.example` to `.env` and fill in
the same values. The launcher reads this file only into its child processes; it
does not display or log the values. Existing PowerShell environment variables
take precedence over `.env`.

The tool is exposed only by the private `rino_mcp.switchbot` stdio MCP server.
SillyTavern never registers or invokes it directly. `home.lock_door` is held by
the Rino Agent Service until its MAF approval flow has completed.

`logs/home-actions.jsonl` contains audit entries and never includes credentials or device IDs. There is no `unlock_door` function, schema, route, or adapter operation.

For an infrared air conditioner, `set_temperature(26)` sends SwitchBot's required
`setAll` parameter `26,1,3,on` (26°C, auto mode, medium fan, on).
