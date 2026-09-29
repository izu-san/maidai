# MaidAI 開発ガイド

このファイルはリポジトリ全体に適用する。より下位の `AGENTS.md` が存在する場合は、そちらを優先する。

## プロジェクトの目的と構成

MaidAI は、ローカルで動作する梨乃の会話 UI、Agent、安全な外部ツール連携、生活連携基盤を組み合わせるプロジェクトである。主要な責務は次のとおり。

| 場所 | 責務 |
|---|---|
| `rino_agent/` | FastAPI の Agent Service、MAF、セッション、承認、ポリシー、監査、イベント待機 |
| `rino_mcp/` | SwitchBot / OBS / ComfyUI / Windows の MCP サーバー |
| `rino_life/` | 生活イベント、消耗品、PC 監視、通知、PostgreSQL / NATS 連携 |
| `rino_event_bus/` | TypeScript 製ローカルイベントバス |
| `rino_launcher/` | 起動ハブ（`Start-MaidAI.ps1`）を操作する PySide6 デスクトップウィジェット。サービス定義は持たない |
| `contracts/` | バージョン付きイベント JSON Schema |
| `infra/` | Rino Life 用 Docker Compose と環境設定 |
| `docs/` | 利用者向け案内、設計、運用資料。入口は `docs/README.md` |
| `tests/` | Python の回帰・統合テスト |

全体像と現在有効な機能は `docs/getting-started/リポジトリ概要と梨乃の使い方.md` を最初に確認する。設計上の方針と実際の実装・設定が異なる場合は、コード、`rino_agent/config/*.yaml`、Compose 設定を現状の根拠とし、ドキュメントの差分を修正する。

## 変更時の基本方針

- 既存のユーザー変更・生成物を勝手に削除、上書き、巻き戻ししない。
- 変更範囲を小さく保ち、既存の責務境界を越える大規模な再設計は明示的な依頼がある場合だけ行う。
- 秘密情報をコード、ドキュメント、テスト、監査ログに書かない。`.env`、トークン、実デバイス ID、個人データ、会話全文、未加工スクリーンショットをコミット対象にしない。
- HTTP の新規公開や LAN バインドは既定で行わない。既存のローカル専用境界（`127.0.0.1`、stdio MCP、Bearer トークン）を維持する。
- 外部操作の成功は、可能なら対象 API / 状態取得で検証する。検証不能なら成功と断定しない。

## Agent・MCP の安全制約

- 新しい外部ツールは `rino_mcp/` の明確な MCP 境界で提供し、任意コマンド実行や任意 URL / API パスを受け付けるツールを作らない。
- MCP サーバーは内部信頼・stdio 接続を基本とし、`rino_agent/config/mcp.yaml` と `policy.yaml` の両方を整合させる。
- ツール追加・変更時はリスク分類、承認要否、引数検証、許可リスト、監査、実行後検証を検討し、必要なテストを追加する。
- `home.unlock_door` は提供しない。施錠、温度変更、配信・録画操作などの承認ルールを緩和しない。
- Agent の再起動後に、保留中承認や高リスク操作を自動再開させない。
- Vision 由来の情報は確認が必要な候補として扱い、それだけで家電操作や生活状態の確定を行わない。

## Rino Life・イベント契約

- 状態変更は可能な限りイベントとして扱い、Rino Life の HTTP 書き込み境界と Outbox / NATS の流れを迂回しない。
- イベント種別・ペイロードを変更する場合は、対応する `contracts/` の Schema、Pydantic 検証、producer、consumer、テストを同時に更新する。
- 既存のメジャー版 Schema の意味を破壊的に変更しない。破壊的変更は新しい subject と `*.v2.schema.json` などの新バージョンで行う。
- イベント payload は 16 KiB 上限を守り、認証情報、会話全文、未加工画像を含めない。
- 消耗品・通知・PC 監視の変更では、重複排除、クールダウン、quiet hours、優先度、冪等性を損なわない。

## データベースとインフラ

- スキーマ変更には Alembic migration を追加し、既存 migration を書き換えない。
- `infra/compose.life.yaml` のポートは loopback に限定する。パスワードは `infra/.env.life` に置き、例示用の値を実環境で使わない。
- 起動方式や必要な環境変数を変えた場合、`Start-MaidAI.ps1`、`Initialize-RinoAgent.ps1`、該当 Runbook の整合性を確認する。

## ドキュメント更新は実装の一部

基盤、機能、API、起動方法、設定、セキュリティ境界、利用可能な自然言語指示、通知内容を追加・変更・有効化・無効化した場合、同じ変更でドキュメントを更新する。計画・将来案を、利用可能な現行機能として書かない。

最低限、次の対応表に従う。

| 変更内容 | 更新する資料 |
|---|---|
| 技術スタック、構成、現行の有効機能、梨乃への指示例、通知の到達範囲 | `docs/getting-started/リポジトリ概要と梨乃の使い方.md` |
| Agent API、セッション、承認、WebSocket | `docs/operations/Rino_Agent_Service_API.md`、必要に応じて `docs/features/エージェント機能一覧.md` |
| MCP の有効化、ツール、許可リスト、運用 | `docs/operations/Rino_MCP_Operations.md`、`docs/features/エージェント機能一覧.md` |
| 起動プロファイル、環境変数、Docker / ポート | `docs/getting-started/起動ハブの使い方.md`、該当 README / Runbook |
| Rino Life、DB、イベント、通知、PC / Vision | `rino_life/README.md`、`docs/architecture/梨乃_生活連携基盤_仕様書.md`、必要に応じて詳細設計 |
| イベント Schema | `contracts/README.md` と該当する設計資料 |

`docs/getting-started/リポジトリ概要と梨乃の使い方.md` には、利用者に見える変更を必ず反映する。同ファイル末尾の「改訂履歴」には、変更日、概要、影響範囲を新しい順で追記する。ほかの主要ドキュメントにも改訂履歴があれば、同じ変更を記録する。単なる誤字修正など利用者への影響がない変更は、改訂履歴を省略してよい。

## 検証

変更に応じて、最小限かつ関連する検証を実行する。

```powershell
# Python の関連テスト
py -3.13 -m pytest tests

# Rino Life 基盤の確認（環境を起動済みの場合）
py -3.13 tools/verify_life_phase0.py assert-ready

# TypeScript Event Bus
Set-Location rino_event_bus; npm test
```

外部サービス、資格情報、モデル、Docker が必要で実行できない検証は、実行していない理由を報告し、少なくとも静的な設定・契約・関連ユニットテストを確認する。

## 完了時の報告

変更したファイル、利用者に見える挙動の変更、実行した検証と未実行の検証を簡潔に報告する。安全制約、既定で無効な統合、通知の最終配送が未接続である事実を、実装以上に利用可能だと表現しない。
