# 梨乃 Event Bus ガイド

## 目的と適用範囲

`rino_event_bus` は、梨乃コンポーネント内の状態変化を疎結合に通知するための、プロセスローカルな Event Bus である。実装は `EventEmitter2` を使用し、イベント名の wildcard 購読を有効にしている。

現段階では Redis、BullMQ、NATS、MQTT、永続キューは使用しない。配信保証、リトライ、イベント保存は提供しないため、イベントを受け取れなかった場合に業務上の不整合が生じる処理や、プロセス再起動をまたぐ処理には使用しない。

現在の `rino_agent` は Python/FastAPI の別プロセスであり、この TypeScript Event Bus を直接共有しない。Vision、SwitchBot、Agent などを移行する際は、同じ Node.js プロセス内のコンポーネントから始める。Python との接続は `AgentEventBridge` の loopback HTTP adapter が Event Bus の envelope を既存 `/events` schema へ変換して行う。アダプタを追加しても Event Bus のイベント契約は変更しない。

## 配置と利用開始

パッケージは `rino_event_bus` にある。アプリケーション側は EventEmitter2 を直接 import せず、必ず `eventBus` または `createEventBus()` を使う。

```ts
import { eventBus } from "@rino/event-bus";

eventBus.emit("vision.screen_changed", {
  source: "screen-vision",
  payload: { windowTitle: "Example Game", capturedAt: Date.now() },
});
```

通常のアプリケーションでは共有インスタンス `eventBus` を使う。独立したテスト、または一時的な隔離環境では `createEventBus()` を使う。

## イベント envelope

すべての listener には、次の形に正規化されたイベントが渡される。

```ts
{
  id: string;
  type: string;
  timestamp: number;
  source: string;
  priority?: number;
  payload: unknown;
}
```

発行時に渡すのは `source` と `payload` である。`id` を省略すると UUID、`timestamp` を省略すると `Date.now()` の Unix epoch milliseconds が設定される。`type` は必ず `emit()` の第1引数が採用される。

```ts
eventBus.emit("agent.action_completed", {
  source: "rino-agent",
  priority: 2,
  payload: { actionId: "act_123", tool: "home.set_light", result: "verified" },
});
```

`payload` はイベント固有のデータだけを入れる。`type`、時刻、発行元、相関 ID などの共通情報を `payload` に重複させない。秘密情報（API token、認証ヘッダー、SwitchBot の credential、個人情報を含む画面内容）は payload に含めない。

`priority` は任意である。使用する場合は、プロジェクト内で `1` を最高、`5` を最低とする。priority は現在配信順序やリトライを変えないため、緊急処理が必要な場合は listener 側で明示的に扱う。

## 命名規則

イベント名は小文字の `domain.action` 形式にする。区切り文字は `.` であり、`snake_case` は各セグメント内だけに使用する。

| domain | 対象 | 例 |
| --- | --- | --- |
| `vision` | 画面認識・検出 | `vision.screen_changed`, `vision.game_detected`, `vision.error_detected` |
| `game` | ゲームの状態 | `game.started`, `game.stopped` |
| `pc` | PC/OS 状態 | `pc.active_window_changed` |
| `switchbot` | SwitchBot センサー状態 | `switchbot.co2_changed` |
| `agent` | Agent の行動ライフサイクル | `agent.action_started`, `agent.action_completed`, `agent.action_failed` |
| `memory` | 記憶の作成・更新 | `memory.created`, `memory.updated` |
| `context` | Agent に渡す前の集約状態 | `context.updated` |
| `system` | ランタイムの状態・障害 | `system.error` |

新規イベントは、既存 domain に属するなら `domain.過去形または状態変化` の形式で追加する。例: `vision.text_detected`、`switchbot.temperature_changed`。新しい domain を増やす場合は、所有コンポーネントと payload 契約をこの文書に追記する。

追加済みの主要 payload 契約は `rino_event_bus/src/event-bus.ts` の `RinoEventPayloads` を正とする。`confidence` は 0〜1、`temperatureC` は Celsius、`humidityPercent` は %、`co2Ppm` は ppm、`idleSeconds` は秒である。

`vision.screen.changed` のように 3 セグメント以上へ細分化しない。将来 `vision.*` を購読する利用者が、Vision 全体を一貫して扱えることを優先する。

## 購読、解除、非同期 listener

```ts
import { eventBus, type RinoEvent } from "@rino/event-bus";

const onVision = (event: RinoEvent) => {
  console.log(event.type, event.payload);
};

// Vision ドメインのすべてを受け取る。`*` は 1 セグメントに一致する。
eventBus.on("vision.*", onVision);

// 不要になったら同一の関数参照で解除する。
eventBus.off("vision.*", onVision);

// 一度だけ受け取る。
eventBus.once("game.started", (event) => console.log(event));

// Promise を返す listener の完了を待つ必要がある場合だけ使用する。
await eventBus.emitAsync("agent.action_completed", {
  source: "rino-agent",
  payload: { actionId: "act_123" },
});
```

通常の `emit()` は同期的に listener を実行する。UI 更新や通知など、発行元が listener の完了を待つ必要がない用途に使用する。listener の例外と長時間処理は発行元へ影響するため、listener 内で適切に例外を処理し、重い処理は別の実行機構へ委譲する。

## 全イベントの監視とログ

開発時の観測には `EventLogger` を使用する。これは `onAny()` 経由で全イベントを監視するだけで、イベントの内容・順序・配信先を変更しない。

```ts
import { eventBus, EventLogger } from "@rino/event-bus";

const eventLogger = new EventLogger();
eventLogger.attach(eventBus);

// 終了処理・テストの cleanup 時
eventLogger.detach(eventBus);
```

本番では、構造化ログへ送る `EventLogSink` を渡す。payload を記録する sink は必ず秘匿情報のマスキングとサイズ制限を行う。

```ts
new EventLogger({
  info: (message, event) => appLogger.info({ ...event, payload: redact(event.payload) }, message),
}).attach(eventBus);
```

## 新規イベント追加の手順

1. domain とイベント名が命名規則に合うことを確認する。
2. `payload` の最小契約（必須・任意フィールド、型、単位）をこの文書または所有コンポーネントの仕様に記載する。
3. `src/event-bus.ts` の `RinoEventType` にイベント名を追加する。末尾の `(string & {})` により未登録イベントも動作するが、主要イベントは補完・レビューのため列挙する。
4. 発行箇所では `eventBus.emit()` のみを使用し、EventEmitter2 を直接使わない。
5. 正確なイベント名の listener と、必要に応じ wildcard listener のテストを追加する。
6. 全イベント logger を有効にして、実際の envelope と秘匿情報の扱いを確認する。

## 既存コンポーネントの段階的な移行

一度に全面移行しない。各コンポーネントで、まず既存処理の完了後に「通知のみ」のイベント発行を追加し、既存の制御フローを残す。イベントを受けて元の制御フローを置換するのは、発行・購読・障害時の挙動を確認してからにする。

| 対象 | 最初に追加するイベント | payload の例 | 注意点 |
| --- | --- | --- | --- |
| Vision | `vision.screen_changed` | `windowTitle`, `captureId`, `changedRegions` | 画像本体や OCR 全文を無制限に流さない |
| Vision | `vision.game_detected` | `gameId`, `gameName`, `confidence` | confidence の範囲を明記する |
| Vision | `vision.error_detected` | `code`, `message`, `confidence` | 秘密情報・画面の個人情報を除く |
| Game | `game.started` / `game.stopped` | `gameId`, `sessionId` | 同一 session の重複発行を避ける |
| PC | `pc.active_window_changed` | `processName`, `windowTitle` | ウィンドウタイトルの秘匿性を確認する |
| SwitchBot | `switchbot.co2_changed` | `deviceId`, `co2Ppm`, `observedAt` | API credential を含めない。閾値・単位を明記する |
| Agent | `agent.action_started` | `actionId`, `sessionId`, `action` | 認可・承認状態を変更する用途にしない |
| Agent | `agent.action_completed` | `actionId`, `result`, `verification` | 成功を推測せず実測の検証結果を使う |
| Agent | `agent.action_failed` | `actionId`, `code`, `retryable` | 元の例外スタックや token を流さない |

Python/FastAPI 側を接続する際は、既存の `/events` の入力 schema と Event Bus envelope の差異をアダプタで吸収する。現在の Python schema は `data` とタイムゾーン付き ISO 8601 timestamp を用いる一方、Event Bus は `payload` と epoch milliseconds を用いる。既存 API の互換性を壊す形で Python schema を先に変更しない。

`AgentEventBridge` はこの変換を担当する標準 adapter である。`vision.*`、`game.*`、`pc.*`、`switchbot.*`、`system.*` を Python の既存 `/events` へ転送する。`memory.*` と `context.*` は raw event のまま Agent に渡さず、`ContextStateAggregator` 等で集約してから必要な consumer だけが利用する。Bridge は listener の失敗を producer へ返さず、Agent 由来の source も再転送しない。

`ContextStateAggregator` は対象 domain の最新 payload が実際に変わった時だけ `context.updated` を発行し、`context.*` 自身を購読しない。このため `context.updated → Agent → context.updated` の循環を作らない。

## テストと確認

Event Bus パッケージのテストは次で実行する。

```powershell
cd D:\AI\MaidAI\rino_event_bus
npm test
```

新規イベントには最低限、(1) envelope の `type` と payload、(2) 想定する wildcard 購読、(3) listener の解除または一度だけの購読、を確認するテストを追加する。
