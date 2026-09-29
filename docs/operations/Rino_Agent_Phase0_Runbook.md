# Rino Agent Phase 0 Runbook

Phase 0 validates only the MAF → KoboldCpp → Gemma 4 function-calling path.
It never loads SwitchBot credentials and exposes no external-action tool.

Run from the project root after KoboldCpp is listening on port 5001:

```powershell
py -3.13 -m rino_agent.poc
py -3.13 -m rino_agent.poc --prompt '現在時刻を教えて。必ず test.get_time を使って。'
py -3.13 -m rino_agent.poc --stream
py -3.13 -m rino_agent.poc --approval
```

The phase passes only if each run invokes its requested tool and produces a
natural-language final answer.  A plain answer without a tool invocation is a
failure: adjust the Gemma chat template/tool settings before building the Agent
Service or connecting any MCP server.
