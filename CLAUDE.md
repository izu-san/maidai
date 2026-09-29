# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

リポジトリ直下の `AGENTS.md`（日本語）が安全制約・ドキュメント更新規則・完了報告の正式なルールである。必ず先に読むこと。下記はそれを補う、コマンドとアーキテクチャの要約。

`GPT-SoVITS/`、`SillyTavern/`、`SillyTavern-extras/`、`koboldcpp/`、`rvc-python/`、`models/` は外部の同梱物・モデルであり、本プロジェクトのコードではない（検索・編集の対象外）。またこのディレクトリは git 管理外なので、既存ファイルを上書きする前に必ず内容を確認する。

## コマンド

Python は 3.13（`py -3.13`）、シェルは PowerShell 前提。

```powershell
py -3.13 -m pip install -r requirements-rino-agent.txt

py -3.13 -m pytest tests                              # 全テスト
py -3.13 -m pytest tests/test_rino_agent_policy.py    # 単一ファイル
py -3.13 -m pytest tests/test_rino_agent_policy.py -k <名前>   # 単一テスト

Set-Location rino_event_bus; npm test                 # tsc ビルド後 node --test（dist/**/*.test.js）

.\Initialize-RinoAgent.ps1                            # 初回のみ: rino_agent\.env に API トークン生成
.\Start-MaidAI.ps1 [-Profile chat|voice|full|docker] [-Status] [-Stop]
py -3.13 tools/verify_life_phase0.py assert-ready     # Rino Life 基盤が起動済みの場合の確認
```

lint / フォーマッタの設定はない。

個別起動（`Start-MaidAI.ps1` が内部で行うもの）:
- Agent Service: `py -3.13 -m uvicorn rino_agent.main:app --host 127.0.0.1 --port 8766`（`rino_agent/Start-AgentService.cmd`）
- Life API: `py -3.13 -m uvicorn rino_life.api:app --host 127.0.0.1 --port 54330`
- Life の DB / NATS: `docker compose --env-file infra/.env.life -f infra/compose.life.yaml up -d`（`-Profile docker`）→ `py -3.13 -m alembic upgrade head` → `py -3.13 -m rino_life.nats_setup`。他に `python -m rino_life.outbox`（Outbox → NATS publisher）、`python -m rino_life.notifications`（通知ルーター）を別プロセスで起動する。

`Start-MaidAI.ps1` は `.env`（`rino/home/.env`、`rino_agent/.env`、`infra/.env.life`）から、スクリプト内 `$allowedNames` に列挙された変数だけを読み込む。新しい環境変数を追加したらこの許可リストにも加える。

## アーキテクチャ

会話 UI は SillyTavern（+ KoboldCpp / 音声系）で、そこから梨乃の Agent Service を呼ぶ。以降は複数ファイルにまたがる全体像。

**Agent Service（`rino_agent/`）** — FastAPI（loopback のみ、Bearer トークン）。`main.py` の `lifespan` が Microsoft Agent Framework の `Agent` を構築し、`rino_agent/config/mcp.yaml` で有効な MCP サーバーを stdio で子プロセスとして接続する（`mcp.py`）。`switchbot` MCP は必須。すべてのツール呼び出しは `RinoPolicyMiddleware`（`middleware.py`）を通り、`policy.py` がリスク分類（READ_ONLY/LOW/MEDIUM/HIGH）と承認要否を決め、`sessions.py` が保留中承認を管理し、`audit.py` が（秘匿化した）監査ログを書く。ツールのリスク/承認は `config/policy.yaml` の `tools:` に定義される。`events.py` はイベント待機タスクの永続化、`workflows.py` は MAF ワークフロー（睡眠・イベント通知）、`websocket.py` は UI 向けイベント配信、`image_generation.py` は非同期画像生成（既定で無効）。

**MCP サーバー（`rino_mcp/`、`rino_life/mcp_server.py`）** — SwitchBot / OBS / ComfyUI / Windows と life。すべて stdio の内部信頼プロセスで HTTP を公開しない。新ツールは `mcp.yaml`（サーバー有効化）と `policy.yaml`（ツール別リスク）の両方に登録しないと整合しない。OBS / ComfyUI / Windows は既定で `enabled: false`。

**Rino Life（`rino_life/`）** — 生活イベント基盤。状態変更は必ず Life API の `POST /events`（唯一の書き込み境界）を通り、検証後に履歴・スナップショット・Outbox 行を単一トランザクションで書く。`outbox.py` が JetStream（NATS）へ発行し、`notifications.py` などの durable consumer が購読する。LLM 向けの `LifeTools`（`tools.py`）は DB / NATS のハンドルを持たない。通知の最終配送はアダプタ注入で、チャット UI へは未接続。DB スキーマは `alembic/versions/`（既存 migration は書き換えない）。

**イベント契約（`contracts/`）** — バージョン付き JSON Schema（`*.v1.schema.json`）。`life-envelope.v1` を共通エンベロープとし、`rino_life/contracts.py` の検証、producer、consumer、テストと常にセットで変更する。破壊的変更は新 subject + `v2` schema。

**Event Bus（`rino_event_bus/`）** — TypeScript のローカルイベントバス。`switchbot-nats-bridge.ts` が SwitchBot 観測をローカルバスから JetStream へ一方向に転送する（購読しないのでループしない）。`agent-event-bridge.ts` は Agent Service との橋渡し。

**起動ウィジェット（`rino_launcher/`）** — PySide6 のデスクトップウィジェット（`Start-MaidAIWidget.cmd`、依存は `requirements-rino-launcher.txt`）。`Start-MaidAI.ps1 -Status -Json` / `-Component <名前> -Action start|stop|restart` を子プロセスで呼ぶだけで、ポートや起動コマンドの定義は `Start-MaidAI.ps1` 側にのみ置く。`status_model.py` は Qt 非依存（テスト対象）。

**ドキュメント** — 入口は `docs/README.md`、現行機能の正は `docs/getting-started/リポジトリ概要と梨乃の使い方.md`。設計文書と実装が食い違う場合は、コード・`rino_agent/config/*.yaml`・Compose を正とする。機能変更時は `AGENTS.md` の対応表に従い、同ファイル末尾の改訂履歴も更新する。

## テスト

`tests/` は pytest（conftest なし）。`test_rino_agent_*`（Agent・ポリシー・MCP 接続・承認・監査）、`test_life_phase0〜5`（Rino Life の各フェーズ）、`test_switchbot_mcp.py` / `test_home_tool.py`、`test_future_mcp_allowlists.py`（未有効 MCP の許可リスト）で構成される。外部サービス・実機・Docker が必要な検証は、実行できない理由を報告する。
