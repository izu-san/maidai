# 画像生成ジョブの骨子

`POST /images/generate` は、SillyTavernが梨乃の「描いてくるね」メッセージを表示した直後に呼ぶ非同期ジョブAPIです。設定済みの固定テンプレートだけをComfyUIへ投入し、呼び出し側はワークフロー、ノードID、実行コマンド、出力パスを指定できません。

```text
SillyTavern: ユーザーの「描いて」依頼を検出して通常返信を中止
  -> 開始メッセージを会話へ表示
  -> POST /api/rino-image/generate
  -> SillyTavernのローカルプロキシが POST /images/generate { "prompt": "..." }
  -> KoboldCpp停止 -> ComfyUI起動 -> API workflow投入
  -> 完了画像を公開用ディレクトリへコピー
  -> ComfyUI停止 -> KoboldCpp再起動
  -> GET /api/rino-image/jobs/{job_id} をポーリング
  -> 完了画像を開始メッセージに添付して会話に表示
```

ブラウザ側はAgent APIトークンを保持しない。SillyTavernの `/api/rino-image` が、起動時に継承した `RINO_AGENT_API_TOKEN` を使い、loopbackのAgent Serviceへ転送する。Agent ServiceのURLは既定で `http://127.0.0.1:8766`、変更時のみSillyTavern起動環境に `RINO_AGENT_URL` を設定する。

有効化には `rino_agent/.env.example` の `RINO_IMAGE_*` をすべて実値へ置換し、`RINO_IMAGE_GENERATION_ENABLED=true` にします。特に以下は環境ごとに指定が必要です。

- API形式のワークフローファイルと、プロンプト差し込み用ノードID・入力名
- KoboldCpp / ComfyUI のプロセス名、JSON配列形式の固定起動コマンド、各ローカルURL
- ComfyUIの `output` ディレクトリと、SillyTavernが配信する公開用ディレクトリ・URL接頭辞

ジョブ状態は `GET /images/{job_id}` で取得できます。完了時には認証済み `/ws/agent` へ `image.generation_completed`、失敗時には `image.generation_failed` が発行されます。

SillyTavern拡張 `Rino Image Generation` は、梨乃との1対1チャットで「描いて」「イラストを生成して」「画像にして」などを含む依頼を検出する。拡張設定では有効／無効と梨乃の表示名だけを変更できる。画像生成中はKoboldCppが停止するため、その間は梨乃の通常会話は利用できない。
