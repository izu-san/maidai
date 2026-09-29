# 梨乃 × SwitchBot 連携仕様書

- 文書名: 梨乃 SwitchBot Home Integration Specification
- バージョン: 1.0
- 作成日: 2026-09-28
- 対象: 梨乃ローカルAIシステム
- 目的: 梨乃から自宅のSwitchBot機器・家電を安全に参照・操作できるようにする

---

## 1. 概要

本機能は、梨乃に「現実世界の環境状態を取得する能力」と「許可された家電を操作する能力」を追加する。

既存の以下の機能と組み合わせて利用する。

- Memory
- Knowledge Graph
- Game Knowledge RAG
- Screen Vision
- Idle / Event Detection
- SillyTavern上の会話
- 今後実装予定の現実カメラVision

SwitchBot固有のAPI仕様をLLMへ直接露出せず、梨乃専用の抽象化された `Home Tool` を介して操作する。

```text
梨乃 LLM
   │
   ├─ Memory
   ├─ KG
   ├─ RAG
   ├─ Vision
   │
   └─ Home Tool
        │
        └─ SwitchBot Adapter
             │
             └─ SwitchBot OpenAPI
                  │
                  └─ Hub 3 / SwitchBot Cloud / 各デバイス
```

---

## 2. 現在の対象環境

### 2.1 所有デバイス

| デバイス | 用途 | 本連携での扱い |
|---|---|---|
| SwitchBot Hub 3 | 家電制御・ハブ | 対象 |
| SwitchBot CO2センサー | CO2 / 温度 / 湿度取得 | 対象 |
| SwitchBot ツインロック | 玄関施錠 | 制限付き対象 |
| SwitchBot 見守りカメラPlus | 現実Vision候補 | 初期実装対象外 |
| 部屋のライト | Hub 3経由で操作 | 対象 |
| エアコン | Hub 3経由で操作 | 対象 |
| テレビ | Hub 3経由で操作 | 対象 |

### 2.2 初期実装の対象外

以下はVersion 1では実装しない。

- 玄関の解錠
- 見守りカメラPlusからの映像取得
- カメラ映像を利用した自律行動
- LLMから任意のSwitchBot APIを直接呼び出す機能
- デバイス登録・削除
- SwitchBotアカウント設定変更
- ファームウェア更新
- 認証情報のLLMコンテキストへの注入

---

## 3. 基本方針

### 3.1 梨乃からSwitchBot APIを直接操作しない

LLMから見えるToolは、SwitchBot APIそのものではなく梨乃専用APIとする。

例:

```text
home.get_environment()
home.light_on()
home.light_off()
home.aircon_on()
home.aircon_off()
home.set_temperature(26)
home.tv_on()
home.tv_off()
home.get_door_status()
home.lock_door()
```

これにより、将来的にSwitchBot以外のスマートホーム基盤へ移行しても、梨乃側のTool仕様を変更せずAdapterのみを差し替えられる。

---

## 4. 権限モデル

### 4.1 権限レベル

| Level | 分類 | 例 | 原則 |
|---|---|---|---|
| 0 | 読み取り | CO2、温度、湿度、玄関状態 | 自動実行可 |
| 1 | 低リスク操作 | ライトON/OFF、TV OFF | 自動実行可 |
| 2 | 中リスク操作 | エアコン温度変更、TV ON | 条件付き自動実行 |
| 3 | セキュリティ操作 | 玄関施錠 | 原則ユーザー確認 |
| 4 | 禁止操作 | 玄関解錠 | Tool自体を実装しない |

### 4.2 ツインロックの扱い

玄関は特別扱いとする。

許可:

```text
home.get_door_status()
home.lock_door()
```

禁止:

```text
home.unlock_door()
```

`unlock_door()` は「呼び出し禁止」ではなく、**Tool定義そのものを存在させない**。

SwitchBot内部APIに `unlock` が存在しても、SwitchBot Adapterでは公開しない。

### 4.3 施錠の自発実行

初期実装では梨乃の完全自律施錠は行わない。

例:

```text
玄関状態: UNLOCKED

梨乃:
「玄関、まだ開いています。施錠しますか？」

ユーザー:
「お願い」

↓

home.lock_door()
```

将来、自動施錠を行う場合は通常のLLM Toolとは分離し、安全条件を満たす専用Automationとして実装する。

---

## 5. 機能要件

## 5.1 環境情報取得

### Tool

```text
home.get_environment()
```

### 取得項目

```json
{
  "temperature_c": 25.8,
  "humidity_percent": 48,
  "co2_ppm": 823,
  "updated_at": "2026-09-28T13:30:00+09:00"
}
```

### 利用目的

- 室温の把握
- 湿度の把握
- CO2濃度の把握
- 会話への自然な反映
- 換気提案
- エアコン操作判断の補助
- 将来的な環境履歴分析

### 基本動作

環境情報の取得はLevel 0とし、梨乃が必要と判断した場合に自動取得してよい。

---

## 5.2 CO2監視

CO2センサーは原則として読み取り専用とする。

### 初期方針

梨乃はCO2値を取得し、必要に応じてユーザーへ通知または換気を提案する。

例:

```text
CO2: 1300 ppm

梨乃:
「CO2が1300ppmまで上がっています。
少し換気したほうがよさそうです。」
```

### 注意

固定閾値のみで人格的な発言を生成しない。

内部判定:

```text
Sensor Event
    ↓
Rule / Threshold
    ↓
Context Check
    ↓
LLM
    ↓
発言する / 何もしない
```

同じ警告を短時間に繰り返さないよう、Cooldownを設ける。

---

## 5.3 ライト

### Tool

```text
home.light_on()
home.light_off()
```

### 権限

Level 1

### 自発操作

許可する。

ただし、通常の会話中に理由なく頻繁に切り替えない。

例:

```text
ユーザー:
「寝るー」

Intent:
sleep

↓

home.light_off()
```

### 将来拡張

対応可能な場合:

```text
home.set_light_brightness(percent)
home.set_light_color(...)
home.set_light_scene(name)
```

---

## 5.4 エアコン

### Tool

```text
home.aircon_on()
home.aircon_off()
home.set_temperature(celsius)
home.set_aircon_mode(mode)
home.set_aircon_fan(speed)
```

### モード例

```text
auto
cool
dry
fan
heat
```

### 権限

Level 2

### 基本ポリシー

温度変更は原則として会話文脈または明示指示に基づいて行う。

例:

```text
ユーザー:
「暑い」

Environment:
29.1 ℃

梨乃:
「エアコン少し下げます？」

ユーザー:
「お願い」

↓

home.set_temperature(26)
```

### 自動操作

将来的に設定可能。

例:

```text
if temperature >= configured_high_threshold
and user_present
and auto_climate_enabled:

    提案 or 自動操作
```

自動温度変更はユーザー設定によってON/OFFできるようにする。

---

## 5.5 テレビ

### Tool

```text
home.tv_on()
home.tv_off()
```

### 権限

- TV OFF: Level 1
- TV ON: Level 2

### 理由

TV OFFは影響が限定的だが、TV ONは意図せず音や光を発生させる可能性があるため、より慎重に扱う。

### 将来拡張

必要に応じて以下を追加可能。

```text
home.tv_volume_up()
home.tv_volume_down()
home.tv_mute()
home.tv_channel(...)
home.tv_input(...)
```

初期版ではON/OFFのみとする。

---

## 5.6 玄関状態

### Tool

```text
home.get_door_status()
```

### 戻り値

```json
{
  "lock_state": "LOCKED",
  "door_state": "CLOSED",
  "battery_percent": 100,
  "updated_at": "2026-09-28T13:30:00+09:00"
}
```

### 状態候補

実デバイスの値はAdapter内で正規化する。

```text
LOCKED
UNLOCKED
JAMMED
UNKNOWN
```

```text
OPEN
CLOSED
UNKNOWN
```

---

## 5.7 玄関施錠

### Tool

```text
home.lock_door()
```

### 権限

Level 3

### 実行条件

初期版:

```text
ユーザーによる明示指示
    OR
梨乃の提案に対する明示的な了承
```

### 実行後確認

施錠コマンド成功レスポンスのみを信用せず、一定時間後に再度状態確認を行う。

```text
lock_door()
    ↓
wait
    ↓
get_door_status()
    ↓
LOCKED ?
  ├─ YES → 完了
  └─ NO  → エラー通知
```

### 解錠

禁止。

API Wrapperに実装しない。

---

## 6. Home Tool API設計

梨乃が利用する公開インターフェース。

```python
class HomeTool:

    # Read-only
    def get_environment(self): ...
    def get_door_status(self): ...

    # Lighting
    def light_on(self): ...
    def light_off(self): ...

    # Air conditioner
    def aircon_on(self): ...
    def aircon_off(self): ...
    def set_temperature(self, celsius: float): ...
    def set_aircon_mode(self, mode: str): ...
    def set_aircon_fan(self, speed: str): ...

    # Television
    def tv_on(self): ...
    def tv_off(self): ...

    # Security
    def lock_door(self): ...
```

以下は定義しない。

```python
def unlock_door(...):
    ...
```

---

## 7. SwitchBot Adapter

SwitchBot固有処理を担当する層。

```text
Home Tool
   ↓
SwitchBot Adapter
   ├─ Authentication
   ├─ Device Registry
   ├─ Status Normalization
   ├─ Command Translation
   ├─ Retry
   ├─ Rate Limit Handling
   └─ Error Mapping
```

### 7.1 主なSwitchBot OpenAPI

```text
GET  /v1.1/devices
GET  /v1.1/devices/{deviceId}/status
POST /v1.1/devices/{deviceId}/commands
```

SwitchBot APIのデバイス一覧には物理デバイスと赤外線リモコンが含まれる。

ライト、エアコン、テレビがHub 3へ赤外線リモコンとして登録されている場合、`infraredRemoteList` から対象デバイスを取得する。

---

## 8. Device Registry

デバイスIDをLLMへ直接渡さない。

設定ファイルで論理名とSwitchBot Device IDを対応付ける。

例:

```yaml
devices:
  co2_meter:
    type: MeterProCO2
    device_id: "${SWITCHBOT_CO2_DEVICE_ID}"

  room_light:
    type: infrared
    remote_type: Light
    device_id: "${SWITCHBOT_LIGHT_DEVICE_ID}"

  air_conditioner:
    type: infrared
    remote_type: Air Conditioner
    device_id: "${SWITCHBOT_AIRCON_DEVICE_ID}"

  television:
    type: infrared
    remote_type: TV
    device_id: "${SWITCHBOT_TV_DEVICE_ID}"

  entrance_lock:
    type: Lock
    device_id: "${SWITCHBOT_LOCK_DEVICE_ID}"
    allow:
      status: true
      lock: true
      unlock: false
```

---

## 9. 認証情報

SwitchBot OpenAPIの認証情報は環境変数またはSecretsファイルで管理する。

例:

```env
SWITCHBOT_TOKEN=...
SWITCHBOT_SECRET=...
```

禁止:

- Python/JavaScriptソースへの直書き
- SillyTavernのキャラクターカードへの保存
- System Promptへの挿入
- Memoryへの保存
- KGへの保存
- LLMへ値を渡すこと
- ログへToken / Secretを出力すること

---

## 10. Tool Calling

LLMは自然言語から操作意図を抽出する。

例:

```text
ユーザー:
「ちょっと暑いからエアコン26度にして」
```

Tool Call:

```json
{
  "name": "home.set_temperature",
  "arguments": {
    "celsius": 26
  }
}
```

Tool Result:

```json
{
  "success": true,
  "device": "air_conditioner",
  "temperature": 26
}
```

梨乃:

```text
「26度にしましたよ。」
```

---

## 11. Tool Result共通形式

成功:

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

失敗:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "DEVICE_OFFLINE",
    "message": "Air conditioner command failed."
  }
}
```

---

## 12. エラーコード

内部でSwitchBot固有エラーを共通コードへ変換する。

```text
AUTH_ERROR
DEVICE_NOT_FOUND
DEVICE_OFFLINE
DEVICE_UNAVAILABLE
COMMAND_FAILED
STATUS_UNAVAILABLE
RATE_LIMITED
NETWORK_ERROR
TIMEOUT
INVALID_ARGUMENT
PERMISSION_DENIED
SECURITY_POLICY_BLOCKED
UNKNOWN_ERROR
```

例:

```json
{
  "success": false,
  "error": {
    "code": "SECURITY_POLICY_BLOCKED",
    "message": "Unlock operation is not permitted."
  }
}
```

---

## 13. Retry

読み取り系:

```text
最大3回
指数バックオフ
```

操作系:

```text
原則1回
```

理由:

ON/OFFや施錠のような操作を無条件で再送すると、重複実行による予期しない状態変化が発生する可能性がある。

施錠など重要操作では再送よりも状態確認を優先する。

---

## 14. State Cache

環境情報や低リスクな状態は短時間キャッシュ可能。

例:

```text
Environment: 30～60秒
Door Status: 原則リアルタイム取得
Device List: 長時間キャッシュ可
```

セキュリティ関連の判断には古いキャッシュを利用しない。

---

## 15. Event System

将来的にはPollingだけでなくWebhookイベントを利用する。

```text
SwitchBot
   ↓
Webhook
   ↓
Rino Event Bus
   ↓
Event Filter
   ↓
Context Engine
   ↓
梨乃
```

例:

```json
{
  "event": "co2_changed",
  "co2_ppm": 1300
}
```

```json
{
  "event": "door_lock_changed",
  "lock_state": "UNLOCKED"
}
```

---

## 16. 自発行動

SwitchBotイベントをそのままLLMへ送信しない。

以下のパイプラインを通す。

```text
SwitchBot Event
       ↓
Rule Filter
       ↓
Cooldown
       ↓
Importance Evaluation
       ↓
Current Context
       ↓
LLM Decision
       ↓
Speak / Act / Ignore
```

### 例: CO2

```text
CO2 1300 ppm
   ↓
閾値超過
   ↓
前回通知から60分以上
   ↓
ユーザーがPC利用中
   ↓
梨乃へイベント
   ↓
換気提案
```

### 例: 就寝

```text
ユーザー:
「寝る」

   ↓

Intent: sleep

   ↓

Scene:
- TV OFF
- Light OFF
- Air conditioner sleep profile
```

---

## 17. Scene機能

複数操作を一つの論理操作としてまとめる。

### Sleep Scene

```text
home.scene("sleep")
```

想定:

```text
TV OFF
Light OFF
Air Conditioner → Sleep Profile
```

### Gaming Scene

```text
home.scene("gaming")
```

想定:

```text
Light → Gaming Profile
Air Conditioner → Gaming Profile
```

Scene内容はLLMに直接生成させず、設定ファイルで定義する。

---

## 18. 安全設計

### 18.1 Hard Block

コードレベルで禁止する。

```text
Unlock door
API credential disclosure
Device deletion
Account modification
Arbitrary SwitchBot API invocation
```

### 18.2 Soft Block

確認を要求する。

```text
Door lock
Large air-conditioner setting change
Future security-sensitive actions
```

### 18.3 Allow

自動実行可能。

```text
Environment read
Light ON/OFF
TV OFF
Low-risk Scene
```

---

## 19. Confirmation Token

Level 3操作は、直前の会話上の了承を確認する。

例:

```text
梨乃:
「玄関を施錠しますか？」

ユーザー:
「お願い」
```

この場合のみ、短時間有効な内部Confirmationを発行する。

```json
{
  "action": "lock_door",
  "confirmed": true,
  "expires_in_seconds": 30
}
```

古い了承を別の操作へ再利用しない。

---

## 20. Audit Log

すべての操作を記録する。

例:

```json
{
  "timestamp": "2026-09-28T13:35:00+09:00",
  "source": "rino",
  "action": "light_off",
  "target": "room_light",
  "reason": "sleep_intent",
  "confirmed_by_user": false,
  "result": "success"
}
```

Security系:

```json
{
  "timestamp": "2026-09-28T13:40:00+09:00",
  "action": "lock_door",
  "confirmed_by_user": true,
  "result": "success"
}
```

TokenやSecretは記録しない。

---

## 21. Memory / KGとの関係

### Memory

長期的な好みを保存可能。

例:

```text
寝る時はライトを消す
エアコンは睡眠時○℃を好む
```

### KG

現在状態の保存先としては利用しない。

CO2や室温など、秒・分単位で変化する情報はKGに恒久保存しない。

必要ならTime-Series DBまたは専用ログへ保存する。

### 重要

現在の状態を取得するときはMemory/KGではなくSwitchBotから取得する。

```text
現在の室温は？
    ↓
home.get_environment()
```

---

## 22. Visionとの統合

現在のScreen VisionとSwitchBot情報を同時利用可能にする。

例:

```text
Screen Vision:
ゲーム終了を検出

Conversation Context:
深夜

Environment:
室温 27.8℃
CO2 1100 ppm

↓

梨乃:
「今日はもう終わりですか？」
```

ユーザー:

```text
「寝るー」
```

↓

```text
Sleep Scene
```

---

## 23. 将来のCamera Vision

見守りカメラPlusとの連携は別フェーズとする。

構想:

```text
PC Screen Vision ─┐
                  │
Camera Vision ────┼── Rino Context Engine
                  │
Environment ──────┘
                        ↓
                     梨乃 LLM
                        ↓
                     Home Tool
```

Camera Visionにはプライバシー保護を別途設計する。

初期SwitchBot連携には含めない。

---

## 24. Home Assistantへの将来移行

梨乃はSwitchBot Adapterへ直接依存しない。

```text
梨乃
 ↓
Home Tool Interface
 ↓
Adapter
```

現在:

```text
Adapter = SwitchBotAdapter
```

将来:

```text
Adapter = HomeAssistantAdapter
```

これにより将来的に、

- SwitchBot
- Philips Hue
- Nature Remo
- Matter
- その他スマートホーム機器

を統一的に扱える。

---

## 25. 推奨ディレクトリ構成

例:

```text
rino/
├─ home/
│  ├─ __init__.py
│  ├─ tool.py
│  ├─ policy.py
│  ├─ scenes.py
│  ├─ models.py
│  ├─ errors.py
│  │
│  ├─ adapters/
│  │  ├─ __init__.py
│  │  └─ switchbot.py
│  │
│  └─ config/
│     ├─ devices.yaml
│     └─ scenes.yaml
│
├─ events/
│  ├─ bus.py
│  ├─ filters.py
│  └─ cooldown.py
│
└─ logs/
   └─ home-actions.jsonl
```

---

## 26. 設定ファイル例

### devices.yaml

```yaml
provider: switchbot

devices:
  environment:
    alias: co2_meter
    device_id_env: SWITCHBOT_CO2_DEVICE_ID

  light:
    alias: room_light
    device_id_env: SWITCHBOT_LIGHT_DEVICE_ID

  aircon:
    alias: air_conditioner
    device_id_env: SWITCHBOT_AIRCON_DEVICE_ID

  tv:
    alias: television
    device_id_env: SWITCHBOT_TV_DEVICE_ID

  entrance:
    alias: entrance_lock
    device_id_env: SWITCHBOT_LOCK_DEVICE_ID
    permissions:
      read: true
      lock: true
      unlock: false
```

### scenes.yaml

```yaml
scenes:
  sleep:
    actions:
      - tv.off
      - light.off
      - aircon.sleep_profile

  gaming:
    actions:
      - light.gaming_profile
      - aircon.gaming_profile
```

---

## 27. 実装順序

### Phase 1: 認証・接続

- SwitchBot OpenAPI認証
- `/v1.1/devices` 取得
- デバイス一覧表示
- Device Registry作成

### Phase 2: Environment

- CO2取得
- 温度取得
- 湿度取得
- `home.get_environment()`

### Phase 3: Lighting

- Light ON
- Light OFF

### Phase 4: Air Conditioner

- ON/OFF
- 温度設定
- Mode
- Fan Speed

### Phase 5: TV

- ON
- OFF

### Phase 6: Security

- Lock状態取得
- Door状態取得
- 施錠
- 施錠後検証
- Unlock Hard Block

### Phase 7: 梨乃Tool Calling

- Tool Schema
- LLMからの呼び出し
- Tool Result
- 会話への反映

### Phase 8: 自発イベント

- CO2監視
- Cooldown
- Context連携
- Scene

### Phase 9: 将来拡張

- Webhook
- Home Assistant Adapter
- Camera Vision
- Matterデバイス
- 詳細な自動化

---

## 28. Version 1 完了条件

以下をすべて満たした時点でVersion 1を完了とする。

- 梨乃がCO2 / 温度 / 湿度を取得できる
- 梨乃がライトをON/OFFできる
- 梨乃がエアコンをON/OFFできる
- 梨乃がエアコン温度を変更できる
- 梨乃がTVをON/OFFできる
- 梨乃が玄関の施錠状態を確認できる
- 梨乃が明示的了承後に玄関を施錠できる
- 梨乃から玄関を解錠する手段が存在しない
- すべての操作がAudit Logへ記録される
- API Token / SecretがLLMへ渡らない
- SwitchBot固有のDevice IDがLLMへ露出しない

---

## 29. 参照したSwitchBot OpenAPI仕様

2026-09-28時点でSwitchBot公式OpenAPIドキュメントから以下を確認。

- OpenAPI v1.1では物理デバイスと赤外線リモコンを `GET /v1.1/devices` で取得可能
- 物理デバイス状態は `GET /v1.1/devices/{deviceId}/status`
- デバイス操作は `POST /v1.1/devices/{deviceId}/commands`
- 仮想赤外線リモコンとしてTV・エアコン等を操作可能
- Air Conditionerは `setAll` により温度・Mode・Fan・Powerを指定可能
- Meter Pro CO2は温度・湿度・CO2 ppmを取得可能
- Lock APIには `lock` と `unlock` が存在するため、本システムではAdapter層で `unlock` を公開しない

公式ドキュメント:

- https://github.com/OpenWonderLabs/SwitchBotAPI
- https://github.com/OpenWonderLabs/SwitchBotAPI/blob/main/devices/others/virtual-infrared-remote-devices.md
- https://github.com/OpenWonderLabs/SwitchBotAPI/blob/main/devices/sensors/meter-pro-co2.md
- https://github.com/OpenWonderLabs/SwitchBotAPI/blob/main/devices/locks-security/lock.md

---

## 30. 最終アーキテクチャ

```text
                       ┌───────────────┐
                       │    Memory     │
                       └───────┬───────┘
                               │
┌──────────────┐       ┌───────▼───────┐       ┌──────────────┐
│ Screen Vision├──────►│               │◄──────┤      KG      │
└──────────────┘       │   梨乃 Brain   │       └──────────────┘
                       │               │
┌──────────────┐       │      LLM      │       ┌──────────────┐
│ Camera Vision├──────►│               │◄──────┤     RAG      │
│  (将来)      │       └───────┬───────┘       └──────────────┘
└──────────────┘               │
                               ▼
                       ┌───────────────┐
                       │   Home Tool   │
                       └───────┬───────┘
                               │
                       ┌───────▼──────────┐
                       │ Security Policy  │
                       └───────┬──────────┘
                               │
                     ┌─────────▼──────────┐
                     │ SwitchBot Adapter  │
                     └─────────┬──────────┘
                               │
                       SwitchBot OpenAPI
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
          CO2 Sensor          Hub 3         Twin Lock
                               │
                         ┌─────┼─────┐
                         ▼     ▼     ▼
                       Light Aircon  TV
```

この構成では、梨乃はSwitchBotそのものを操作するのではなく、常に `Home Tool + Security Policy` を経由して現実世界へ作用する。

これを本連携の基本原則とする。
