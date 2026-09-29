# 梨乃 Agent Platform 仕様書
## Microsoft Agent Framework + MCP 採用版

- 文書名: Rino Agent Platform Specification
- バージョン: 2.0
- 作成日: 2026-09-28
- 対象: 梨乃ローカルAIシステム
- 方針: Agent基盤を全面自作せず、Microsoft Agent Framework（以下 MAF）を中核に採用する
- Tool統合方式: MCP（Model Context Protocol）を標準境界として採用
- LLM実行基盤: KoboldCpp + Gemma 4（OpenAI Chat Completions互換API経由）
- 本仕様の目的: 梨乃固有機能を維持したまま、Agent実行・Workflow・承認・Checkpoint・Tool統合をOSS基盤へ委譲する

---

# 1. 結論

梨乃のAgent化では、独自Agent Runtimeをゼロから実装しない。

以下の構成を標準とする。

```text
SillyTavern / 梨乃UI
        │
        ▼
Rino Agent Service
        │
        ├─ Microsoft Agent Framework
        │    ├─ Agent
        │    ├─ Workflow
        │    ├─ Tool Calling
        │    ├─ Human-in-the-Loop Approval
        │    ├─ Middleware
        │    ├─ Session / State
        │    └─ Checkpoint
        │
        ├─ Rino Context Layer
        │    ├─ Memory
        │    ├─ Knowledge Graph
        │    ├─ Game Knowledge RAG
        │    ├─ Screen Vision
        │    └─ Idle / Event Detection
        │
        ├─ Rino Policy Layer
        │    ├─ Risk分類
        │    ├─ Tool Allow / Deny
        │    ├─ Confirmation条件
        │    └─ 自発行動制限
        │
        └─ MCP Clients
             ├─ switchbot-mcp
             ├─ obs-mcp
             ├─ comfyui-mcp
             ├─ windows-mcp
             └─ future-mcp
```

LLM:

```text
Microsoft Agent Framework
        │
        ▼
OpenAI Chat Completions互換API
        │
        ▼
KoboldCpp
        │
        ▼
Gemma 4
```

---

# 2. 採用理由

## 2.1 全面自作を避ける理由

旧仕様では以下を独自実装する想定だった。

```text
Agent Runtime
Planner
Tool Registry
Policy Engine
Task Queue
Event Bus
Executor
Observer
Verifier
Checkpoint
Approval
Audit
```

このうち、汎用Agent基盤として既に成熟した実装が存在する部分はOSSへ委譲する。

MAFへ委譲する対象:

```text
Agent実行ループ
Tool Calling
Workflow
Session
Human-in-the-Loop
Tool Approval
Pause / Resume
Checkpoint
Middleware
MCP接続
```

梨乃専用として残す対象:

```text
Memory統合
Knowledge Graph統合
Game RAG統合
Screen Vision統合
Idle / Event Detection
Risk分類ルール
自発行動ルール
Toolごとの安全条件
Observation / Verification方針
梨乃人格
SillyTavern連携
```

---

# 3. Microsoft Agent Framework の役割

MAFを梨乃Agentの共通実行基盤とする。

主な役割:

```text
Agent生成
Agent Session
Tool Calling
Workflow
Tool Approval
Human-in-the-Loop
Checkpoint
Pause / Resume
Middleware
MCP Tool接続
```

梨乃独自のAgent Runtimeを作るのではなく、

```text
Rino Agent Service
    ↓
Microsoft Agent Framework
```

の上に梨乃固有機能を実装する。

---

# 4. MCP の役割

MCPは外部Toolとの標準接続境界とする。

MCP Serverは以下を公開する。

```text
Tool Name
Description
Input Schema
Output
```

梨乃側は外部システム固有APIを直接呼ばない。

```text
梨乃 Agent
   ↓
MCP Client
   ↓
MCP Server
   ↓
対象システム
```

---

# 5. MCP化の基本方針

原則として、独立した外部システムはMCP Server化する。

対象:

```text
SwitchBot
OBS
ComfyUI
Windows操作
将来のHome Assistant
将来の外部サービス
```

一方、Agent Service内部だけで完結する軽量処理はMAF Function Toolでもよい。

例:

```text
現在時刻取得
内部状態参照
Session状態取得
軽量な変換処理
```

---

# 6. SwitchBotの位置付け

SwitchBotはAgent配下へ統合する。

推奨構成:

```text
Rino Agent Service
        │
        ▼
Microsoft Agent Framework
        │
        ▼
Rino Policy Middleware
        │
        ▼
switchbot-mcp
        │
        ▼
SwitchBot API / Hub 3
        │
        ├─ CO2 Sensor
        ├─ Light
        ├─ Air Conditioner
        ├─ TV
        └─ Twin Lock
```

SwitchBotをAgent外の特別処理として実装しない。

理由:

- 他Toolと同じ承認フローを使える
- AgentのWorkflowに組み込める
- Auditしやすい
- 将来Home Assistantへ交換しやすい
- Tool Schemaを標準化できる
- 梨乃本体からSwitchBot固有APIを分離できる

---

# 7. SwitchBot MCP Tool

初期Tool:

```text
home.get_environment
home.light_on
home.light_off
home.aircon_on
home.aircon_off
home.set_temperature
home.tv_on
home.tv_off
home.get_door_status
home.lock_door
```

禁止:

```text
home.unlock_door
```

`unlock_door` はPolicyで拒否するだけではなく、MCP ServerからTool自体を公開しない。

---

# 8. SwitchBot Risk Policy

| Tool | Risk | 自動実行 |
|---|---|---|
| home.get_environment | READ_ONLY | 可 |
| home.get_door_status | READ_ONLY | 可 |
| home.light_on | LOW | 可 |
| home.light_off | LOW | 可 |
| home.aircon_on | LOW | 条件付き可 |
| home.aircon_off | LOW | 条件付き可 |
| home.set_temperature | MEDIUM | 原則確認 |
| home.tv_off | LOW | 可 |
| home.tv_on | MEDIUM | 原則確認 |
| home.lock_door | HIGH | 必ず確認 |
| home.unlock_door | BLOCKED | Toolなし |

---

# 9. Tool Approval

MAFのHuman-in-the-Loop / Tool Approval機構を利用する。

例:

```text
Goal
 ↓
Agentが home.lock_door を選択
 ↓
Rino Policy
 ↓
HIGH
 ↓
Approval Required
 ↓
Workflow Pause
 ↓
SillyTavernへ承認要求
 ↓
ユーザー承認
 ↓
Resume
 ↓
Tool実行
```

HIGH Risk ToolはMAF側でも承認必須Toolとして定義する。

---

# 10. 二重安全設計

安全制御を1箇所だけに依存しない。

```text
第1層:
MCP Server側のTool公開制限

第2層:
Rino Policy Middleware

第3層:
MAF Tool Approval

第4層:
実行後Verification
```

例: 玄関

```text
unlock:
MCP ServerにToolなし

lock:
MCP ServerにToolあり
↓
Policy = HIGH
↓
Approval必須
↓
実行
↓
状態再取得
↓
LOCKED確認
```

---

# 11. LLM構成

現在のローカルLLM構成を維持する。

```text
Gemma 4
 ↓
KoboldCpp
 ↓
OpenAI Chat Completions互換API
 ↓
Microsoft Agent Framework
```

MAF PythonではOpenAI互換 `base_url` を指定してローカル推論サーバーへ接続する。

例:

```python
OpenAIChatCompletionClient(
    base_url="http://127.0.0.1:5001/v1/",
    api_key="not-needed",
    model="koboldcpp/gemma-4-26B_q4_0-it",
)
```

実際のPort / Model名は現在のKoboldCpp設定に合わせる。

---

# 12. KoboldCpp Tool Calling

KoboldCppはMCP Tool Callingをサポートしているが、本構成ではTool Routingの中心をMAF側に置く。

推奨:

```text
KoboldCpp
= LLM inference

MAF
= Agent orchestration + Tool calling + Approval

MCP
= Tool protocol
```

KoboldCpp側で直接MCPを実行する構成は採用しない。

理由:

```text
PolicyをMAF側へ集約したい
WorkflowをMAFで管理したい
CheckpointをMAFで管理したい
Tool Approvalを一元化したい
Auditを一元化したい
```

---

# 13. Tool Calling互換性テスト

MAF導入時に最初に以下を検証する。

```text
MAF
 ↓
OpenAI Chat Completion
 ↓
KoboldCpp
 ↓
Gemma 4
```

テストTool:

```text
test.echo
```

Schema:

```json
{
  "text": "hello"
}
```

確認項目:

```text
1. Tool Schemaがモデルへ渡る
2. Gemma 4がTool Callを生成する
3. MAFがTool Callを認識する
4. Toolが実行される
5. Tool Resultがモデルへ戻る
6. 最終自然言語応答が生成される
```

ここをAgent開発の最初のGateとする。

---

# 14. Rino Agent Service

MAFを直接SillyTavern拡張へ埋め込まない。

独立したローカルServiceとして実装する。

```text
SillyTavern
   ↓ HTTP / WebSocket
Rino Agent Service
   ↓
MAF
```

利点:

```text
SillyTavern再起動とAgent状態を分離
MCP Serverを一元管理
Checkpointを保持
Eventを受信可能
テストしやすい
将来UIを変更しやすい
```

---

# 15. Rino Agent Service API

初期API例:

```text
POST /agent/run
POST /agent/approve
POST /agent/reject
POST /agent/cancel

GET  /agent/session/{id}
GET  /agent/tasks
GET  /agent/tools

POST /events
```

WebSocket:

```text
/ws/agent
```

用途:

```text
Streaming
Approval Request
Tool Status
Task Complete
Agent Event
```

---

# 16. 梨乃LLMとの責務分離

梨乃LLM:

```text
会話
人格
意図理解
Goal生成
Tool選択の候補
ユーザーへの説明
```

MAF / Rino Agent Service:

```text
Tool実行
Workflow
State
Approval
Checkpoint
Policy適用
Timeout
Retry
Audit
```

MCP Server:

```text
実システムとの通信
引数検証
固有API変換
固有安全制御
```

---

# 17. Existing Memoryとの統合

既存MemoryをMAF標準Memoryへ移行しない。

現状の梨乃Memoryを維持する。

```text
Existing Memory
      ↓
Rino Context Builder
      ↓
Agent Context
```

MAFはAgent実行基盤として利用し、人格記憶のSingle Source of Truthにはしない。

---

# 18. Knowledge Graphとの統合

KGも既存実装を維持する。

Agent実行前に必要な関連情報だけ取得する。

例:

```text
Goal:
「いつものComfyUIワークフロー開いて」

 ↓

Context Builder

 ↓

KG:
preferred_workflow = Anima Quality

 ↓

Agent
```

---

# 19. Game Knowledge RAGとの統合

Game Knowledge RAGはAgent Frameworkへ移植しない。

既存RAGをContext Sourceとして接続する。

```text
Game Event
 ↓
Context Builder
 ↓
必要なGame RAGだけ検索
 ↓
Agent Context
```

Agent実行とゲーム知識検索を分離する。

---

# 20. Visionとの統合

Screen Visionは2つの用途を持つ。

```text
1. Event Source
2. Observer / Verifier
```

Event Source例:

```text
vision.game_run_completed
vision.generation_completed
vision.idle_detected
```

Observer例:

```text
OBSが画面に出た
指定Workflowが開いた
エラーダイアログが出た
```

---

# 21. Verification優先順位

実行後確認は以下の優先順位とする。

```text
1. 対象システム公式API
2. MCP Serverから取得した状態
3. OS / Process状態
4. File状態
5. Screen Vision
6. LLM推測
```

LLM推測だけで成功判定しない。

---

# 22. Workflow

複数Step操作はMAF Workflowとして実装する。

例: OBS起動

```text
CheckProcess
    ↓
Running?
 ├─ Yes → Complete
 └─ No
      ↓
   LaunchOBS
      ↓
   CheckProcess
      ↓
   Verify
```

---

# 23. Workflowと単純Tool Callingの使い分け

単発Tool:

```text
音量変更
ライトOFF
CO2取得
スクリーンショット
```

Workflow:

```text
ComfyUIを開いてWorkflowをロード
配信準備
就寝Scene
生成終了後に保存して通知
玄関施錠 + 状態確認
```

---

# 24. Agent Mode

梨乃側の独自設定として以下を維持する。

```text
PASSIVE
ASSIST
AUTO
```

## PASSIVE

```text
Toolはユーザー明示要求時のみ
```

## ASSIST

```text
READ_ONLY / LOW:
自動実行可

MEDIUM以上:
確認
```

標準モードとする。

## AUTO

```text
許可されたGoalについて
複数Stepを自律実行可
```

ただしPolicyは無効化されない。

---

# 25. Risk Model

Rino Policy Layer独自定義:

```text
READ_ONLY
LOW
MEDIUM
HIGH
CRITICAL
BLOCKED
```

MAF標準Tool Approvalとは別に持つ。

理由:

MAFのApproval機能は「承認が必要か」の実行機構であり、梨乃独自のRisk分類そのものではないため。

---

# 26. Rino Policy Middleware

Policy判定はTool実行直前に必ず通す。

入力:

```text
Tool
Arguments
Agent Mode
Goal Source
Risk
User Confirmation
Current Context
```

出力:

```text
ALLOW
REQUIRE_APPROVAL
DENY
```

---

# 27. Policy例

```yaml
tools:

  home.get_environment:
    risk: READ_ONLY
    allow_autonomous: true

  home.light_off:
    risk: LOW
    allow_autonomous: true

  home.set_temperature:
    risk: MEDIUM
    allow_autonomous: false

  home.lock_door:
    risk: HIGH
    approval: always

  file.delete:
    risk: HIGH
    approval: always

  system.shutdown:
    risk: HIGH
    approval: always

  home.unlock_door:
    risk: BLOCKED
    enabled: false
```

---

# 28. MCP ServerごとのPolicy

MCP Server単位でもTrust Levelを設定する。

例:

```yaml
mcp_servers:

  switchbot:
    trust: internal

  obs:
    trust: internal

  comfyui:
    trust: internal

  third_party_unknown:
    trust: untrusted
```

Untrusted MCPは初期状態で無効。

---

# 29. MCP Server導入ルール

MCP Serverは任意コードを実行できる可能性があるため、以下を必須とする。

```text
Source確認
依存関係確認
固定Version
不要権限を与えない
localhost binding
Firewall
Secret分離
Audit
```

自作MCPを優先する対象:

```text
SwitchBot
OBS
ComfyUI
Windows
```

---

# 30. switchbot-mcp

SwitchBot用MCPは独立プロセスとする。

```text
Rino Agent Service
 ↓ MCP
switchbot-mcp
 ↓
SwitchBot OpenAPI
```

責務:

```text
SwitchBot認証
Device ID隠蔽
論理名マッピング
入力検証
API呼び出し
Result正規化
安全制限
```

---

# 31. switchbot-mcp Security

絶対条件:

```text
Unlock Toolを公開しない
Token / Secretを返さない
Device IDをLLMへ返さない
任意command実行Toolを作らない
任意API Path Toolを作らない
```

---

# 32. OBS MCP

将来:

```text
obs.get_status
obs.start_stream
obs.stop_stream
obs.start_recording
obs.stop_recording
obs.set_scene
```

可能ならOBS WebSocketを利用し、GUI操作を避ける。

---

# 33. ComfyUI MCP

将来:

```text
comfyui.get_status
comfyui.list_workflows
comfyui.open_workflow
comfyui.queue_prompt
comfyui.cancel_prompt
comfyui.get_history
```

可能な限りComfyUI APIを利用する。

---

# 34. Windows MCP

最も慎重に設計する。

初期Tool:

```text
process.check
app.launch
app.close
system.get_volume
system.set_volume
screenshot.capture
file.exists
file.open
```

禁止:

```text
shell.run_arbitrary
powershell.run_arbitrary
cmd.run_arbitrary
registry.write_arbitrary
```

---

# 35. Shell

万能Shell Toolは初期実装しない。

どうしても必要になった場合:

```text
専用High Risk MCP
Allowlist Command
Argument Validation
Approval Required
Working Directory制限
Timeout
Audit
```

を必須とする。

---

# 36. Human-in-the-Loop

MAFのTool Approval機構を利用する。

Approval RequestはSillyTavernへ返す。

例:

```text
梨乃:
「玄関が開いています。施錠しますか？」

User:
「お願い」
```

内部:

```text
MAF Workflow
 ↓
Approval Request
 ↓
Rino Agent Service
 ↓
SillyTavern
 ↓
User Response
 ↓
Rino Agent Service
 ↓
MAF Resume
```

---

# 37. Confirmationと会話

「お願い」「うん」などの自然言語了承は、直前のApproval Requestと紐付ける。

条件:

```text
同一Session
同一Pending Approval
期限内
未使用
```

別Toolへの承認として再利用しない。

---

# 38. Checkpoint

MAFのCheckpoint機能を利用する。

ローカル環境では初期実装として:

```text
FileCheckpointStorage
```

を利用可能。

用途:

```text
長時間Workflow
Human Approval待ち
一時停止
障害復旧
```

---

# 39. Restart Policy

Agent Service再起動後:

安全なWorkflowのみResume候補とする。

禁止:

```text
HIGH Risk Tool実行直前の自動Resume
古いApprovalの再利用
```

Approval Pendingの場合:

```text
再度ユーザー確認
```

を基本とする。

---

# 40. Task Queue

短時間の条件待ちタスクはMAF Workflow + Checkpointで管理する。

例:

```text
「ComfyUIの生成終わったら教えて」
```

```text
WaitEvent
 ↓
comfyui.generation_completed
 ↓
Notify
```

---

# 41. Event Bus

既存Vision / Idle / App EventsをRino Agent Serviceへ送る。

```text
Vision
ComfyUI
OBS
SwitchBot
System
 ↓
Rino Event Gateway
 ↓
Relevant Workflow
```

---

# 42. Event Schema

```json
{
  "type": "vision.game_run_completed",
  "source": "screen_vision",
  "timestamp": "2026-09-28T15:00:00+09:00",
  "data": {
    "game": "AzurLane"
  }
}
```

---

# 43. Event → Agent制限

全EventをLLMへ投げない。

```text
Event
 ↓
Filter
 ↓
Rule
 ↓
Cooldown
 ↓
Relevant Workflow?
 ├─ Yes → Agent
 └─ No  → Drop
```

---

# 44. 自発Agent

梨乃の自発行動は完全自由Agentにしない。

初期のGoal Source:

```text
User Request
Registered Event
Registered Task
Approved Automation
```

LLMが理由なく新規Goalを作り続ける構造は禁止。

---

# 45. 自発Tool制限

自発実行可能:

```text
READ_ONLY
LOW
```

原則確認:

```text
MEDIUM
HIGH
CRITICAL
```

禁止:

```text
BLOCKED
```

---

# 46. Planner

初期実装では「巨大な万能Planner」を独自実装しない。

単純Goal:

```text
Agent Tool Calling
```

複数Step:

```text
MAF Workflow
```

複雑な動的Planが必要になった段階でMAFのAgent Harness / Workflow機能を追加検討する。

---

# 47. Observe → Verify

MAFに任せきらず、梨乃固有のVerification Layerを残す。

理由:

```text
Tool Callが成功
≠
現実の目的達成
```

例:

```text
app.launch("obs")
 ↓
Tool success
 ↓
process.check
 ↓
running
 ↓
Success
```

---

# 48. Verification Tool

MCP Toolとして状態取得Toolを用意する。

例:

```text
obs.get_status
comfyui.get_status
process.check
home.get_door_status
file.exists
```

Workflow内でAction後に明示的に呼ぶ。

---

# 49. Audit Log

Rino Agent Service側で独自Auditを残す。

MAFログだけに依存しない。

保存:

```text
Goal
Tool
Arguments（Secret除外）
Risk
Approval
Result
Verification
Timestamp
Session
```

---

# 50. Secret管理

禁止:

```text
LLM Context
Memory
KG
SillyTavern Prompt
Audit Log
Tool Result
```

保存先:

```text
.env
Windows Credential Manager
専用Secret Store
```

MCP Serverごとに必要なSecretだけ渡す。

---

# 51. Network Boundary

すべてローカルで動かす場合の推奨:

```text
KoboldCpp        127.0.0.1
Rino Agent       127.0.0.1
MCP Servers      local stdio / 127.0.0.1
SillyTavern      local
```

LAN公開が必要なものだけ明示的に許可する。

---

# 52. SillyTavern Integration

SillyTavernはUI / Conversation Layerとして維持する。

役割:

```text
ユーザー会話
梨乃人格表示
Approval UI
Agent Status
Task Result
```

Agent処理はRino Agent Serviceへ委譲する。

---

# 53. SillyTavernからAgentを呼ぶ条件

すべての発言をAgentへ送らない。

Intent Router:

```text
Conversation Only
    ↓
通常LLM

Action Required
    ↓
Rino Agent Service
```

例:

```text
「今日は暑いね」
→ Conversation

「エアコン26度にして」
→ Agent
```

---

# 54. Agent Result

Rino Agent Serviceから構造化結果を返す。

```json
{
  "status": "succeeded",
  "goal": "エアコンを26度に設定",
  "tool": "home.set_temperature",
  "verified": true,
  "summary": "Air conditioner target temperature is 26°C."
}
```

梨乃LLMが自然文へ変換する。

---

# 55. Error Result

```json
{
  "status": "failed",
  "code": "VERIFICATION_FAILED",
  "summary": "Command was sent but the resulting state could not be verified."
}
```

梨乃が勝手に成功扱いしない。

---

# 56. 推奨ディレクトリ

```text
rino-agent/
├─ app/
│  ├─ main.py
│  ├─ api/
│  ├─ websocket/
│  │
│  ├─ agent/
│  │  ├─ factory.py
│  │  ├─ workflows/
│  │  ├─ middleware/
│  │  └─ sessions/
│  │
│  ├─ context/
│  │  ├─ memory.py
│  │  ├─ kg.py
│  │  ├─ rag.py
│  │  └─ vision.py
│  │
│  ├─ policy/
│  │  ├─ engine.py
│  │  ├─ risk.py
│  │  └─ rules.yaml
│  │
│  ├─ mcp/
│  │  ├─ registry.py
│  │  └─ clients.py
│  │
│  ├─ events/
│  │  ├─ gateway.py
│  │  ├─ filters.py
│  │  └─ cooldown.py
│  │
│  ├─ verification/
│  │  └─ strategies.py
│  │
│  └─ audit/
│     ├─ logger.py
│     └─ redaction.py
│
├─ checkpoints/
├─ logs/
└─ config/
   ├─ agent.yaml
   ├─ policy.yaml
   └─ mcp.yaml
```

MCP Servers:

```text
rino-mcp/
├─ switchbot-mcp/
├─ obs-mcp/
├─ comfyui-mcp/
└─ windows-mcp/
```

---

# 57. mcp.yaml

```yaml
servers:

  switchbot:
    enabled: true
    transport: stdio
    trust: internal

  obs:
    enabled: false
    transport: stdio
    trust: internal

  comfyui:
    enabled: false
    transport: stdio
    trust: internal

  windows:
    enabled: false
    transport: stdio
    trust: internal
```

---

# 58. agent.yaml

```yaml
agent:

  mode: assist

  model:
    provider: openai_compatible
    base_url: http://127.0.0.1:5001/v1/
    model: koboldcpp/gemma-4-26B_q4_0-it

  checkpoint:
    provider: file
    path: ./checkpoints

  autonomous_actions:
    max_risk: LOW
```

---

# 59. policy.yaml

```yaml
risk_policy:

  READ_ONLY:
    allowed: true
    approval: false

  LOW:
    allowed: true
    approval: false

  MEDIUM:
    allowed: true
    approval: context

  HIGH:
    allowed: true
    approval: always

  CRITICAL:
    allowed: true
    approval: explicit

  BLOCKED:
    allowed: false
```

---

# 60. Phase 0: Compatibility PoC

最初にここだけ行う。

構成:

```text
MAF
 ↓
KoboldCpp
 ↓
Gemma 4
```

Tool:

```text
test.echo
test.get_time
```

確認:

```text
Tool Calling
Streaming
Session
Approval
```

このPoCが成功するまで大規模実装へ進まない。

---

# 61. Phase 1: Rino Agent Service

実装:

```text
FastAPI等のローカルService
MAF Agent生成
KoboldCpp接続
Session
Streaming
SillyTavern接続
```

---

# 62. Phase 2: Policy

実装:

```text
Risk
Allow / Deny
Approval
Audit
Secret Redaction
```

テスト:

```text
LOW Tool
HIGH Tool
BLOCKED Tool
```

---

# 63. Phase 3: switchbot-mcp

現在実装予定のSwitchBot連携をMCP Serverとして実装する。

最初の実用Agent Toolとする。

実装順:

```text
home.get_environment
home.light_on/off
home.aircon_on/off
home.set_temperature
home.tv_on/off
home.get_door_status
home.lock_door
```

---

# 64. Phase 4: Approval UI

SillyTavernでMAF Approval Requestを扱う。

例:

```text
[梨乃]
玄関を施錠しますか？

[承認] [拒否]
```

自然言語承認も対応可能にする。

---

# 65. Phase 5: Workflow

SwitchBotで最初のWorkflowを作る。

例: sleep

```text
TV OFF
 ↓
Light OFF
 ↓
必要ならAircon
 ↓
各状態Verify
 ↓
Complete
```

玄関施錠はSleep Workflowへ自動挿入しない。

別Approvalとする。

---

# 66. Phase 6: OBS MCP

OBS WebSocketベース。

Action → Status Verifyを実装する。

---

# 67. Phase 7: ComfyUI MCP

既存ComfyUI環境と連携する。

最初のTask:

```text
生成開始
 ↓
生成完了Event
 ↓
Agent Workflow Resume
 ↓
通知
```

---

# 68. Phase 8: Vision Event

既存Screen VisionからEvent Gatewayへ送る。

```text
Vision
 ↓
Event
 ↓
Workflow
```

---

# 69. Phase 9: Windows MCP

必要になったToolだけ追加する。

Raw Mouse / Keyboard操作は後回し。

---

# 70. Version 1 完了条件

以下を満たした時点でRino Agent Platform v1とする。

```text
MAF + KoboldCpp + Gemma 4でTool Calling成功
SillyTavernからAgent Goal送信可能
MCP Server接続可能
Policy Middleware動作
Tool Approval動作
Checkpoint動作
Audit Log動作
switchbot-mcp接続
CO2取得
ライト操作
エアコン操作
TV操作
玄関状態取得
玄関施錠Approval
玄関解錠Toolが存在しない
Action後Verification
```

---

# 71. 旧Agent Core仕様から削除する自作要素

以下は原則として独自再実装しない。

```text
独自Agent Runtime
独自Session Engine
独自Workflow Engine
独自Tool Calling Protocol
独自Approval Runtime
独自Checkpoint Engine
独自MCP Protocol
```

---

# 72. 引き続き自作する要素

```text
Rino Context Builder
Rino Policy
Risk Model
Event Gateway
Vision Integration
Memory / KG / RAG Adapter
Verification Strategy
Audit Redaction
SillyTavern Integration
MCP Servers
梨乃人格
```

---

# 73. 設計上の重要判断

## Agent FrameworkとMCPの責務を混ぜない

```text
MAF
= Agentを動かす

MCP
= Toolへ接続する
```

## KoboldCppにAgent管理を任せない

```text
KoboldCpp
= inference
```

## SillyTavernにWorkflow管理を任せない

```text
SillyTavern
= UI / conversation
```

## SwitchBotに梨乃固有ロジックを入れない

```text
switchbot-mcp
= Device Adapter
```

梨乃固有の判断はAgent側に置く。

---

# 74. 最終アーキテクチャ

```text
┌─────────────────────────────────────────────┐
│               SillyTavern                   │
│            梨乃 Conversation UI             │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│             Rino Agent Service              │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │      Microsoft Agent Framework        │  │
│  │                                       │  │
│  │ Agent / Workflow / Session            │  │
│  │ Tool Calling / Approval / Checkpoint  │  │
│  └─────────────────┬─────────────────────┘  │
│                    │                        │
│  ┌─────────────────▼─────────────────────┐  │
│  │           Rino Policy Layer           │  │
│  │ Risk / Allow / Approval / Block       │  │
│  └─────────────────┬─────────────────────┘  │
│                    │                        │
│  ┌─────────────────▼─────────────────────┐  │
│  │             MCP Clients               │  │
│  └──────────┬────────┬────────┬──────────┘  │
│             │        │        │             │
│  Context:   │        │        │             │
│  Memory     │        │        │             │
│  KG         │        │        │             │
│  RAG        │        │        │             │
│  Vision     │        │        │             │
└─────────────┼────────┼────────┼─────────────┘
              │        │        │
              ▼        ▼        ▼
        switchbot    obs     comfyui      windows
           MCP       MCP       MCP          MCP
              │        │        │            │
              ▼        ▼        ▼            ▼
         SwitchBot    OBS    ComfyUI       Windows


LLM Path:

Rino Agent Service
        │
        ▼
Microsoft Agent Framework
        │
        ▼
KoboldCpp OpenAI-compatible API
        │
        ▼
Gemma 4
```

---

# 75. 不変条件

1. 外部操作は原則Agentを経由する
2. 外部システムは原則MCP境界を持つ
3. MAFをAgent Runtimeとして利用する
4. KoboldCppは推論基盤として扱う
5. Memory / KG / RAG / Visionは既存資産を維持する
6. HIGH Risk ToolはHuman Approval必須
7. BLOCKED Toolは公開しない
8. SwitchBotの玄関解錠Toolは実装しない
9. Tool成功だけでGoal成功としない
10. 可能な限り状態を再取得してVerifyする
11. SecretをLLMへ渡さない
12. MCP Serverを無条件に信用しない
13. 自発行動はLOW以下を基本とする
14. Workflow StateはCheckpoint可能にする
15. Agentの操作履歴をAuditする

以上を梨乃Agent Platformの基本設計とする。

---

# 76. 参考資料

- Microsoft Agent Framework - Get started  
  https://learn.microsoft.com/en-us/agent-framework/get-started/

- Microsoft Agent Framework - Tools  
  https://learn.microsoft.com/en-us/agent-framework/agents/tools/

- Microsoft Agent Framework - MCP Tools  
  https://learn.microsoft.com/en-us/agent-framework/agents/tools/local-mcp-tools

- Microsoft Agent Framework - Human in the Loop  
  https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop

- Microsoft Agent Framework - Tool Approval  
  https://learn.microsoft.com/en-us/agent-framework/agents/tools/tool-approval

- Microsoft Agent Framework - Checkpoints  
  https://learn.microsoft.com/en-us/agent-framework/workflows/checkpoints

- Microsoft Agent Framework - OpenAI-compatible endpoints  
  https://learn.microsoft.com/en-us/agent-framework/hosting/self-hosting/openai-endpoints

- Model Context Protocol Specification  
  https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification

- KoboldCpp Wiki  
  https://github.com/LostRuins/koboldcpp/wiki
