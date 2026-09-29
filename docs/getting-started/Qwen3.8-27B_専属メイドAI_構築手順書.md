# Qwen3.8-27B 専属メイドAI 構築手順書

更新日: 2026-09-27  / 対象: Windows 11 25H2、RTX 4090 24GB、Valheim・Factorioと同時利用

## 0. 到達点と進め方

SillyTavern（会話・キャラクター・記憶）→ KoboldCpp（GGUF推論）→ Qwen3.8-27B。音声は後からローカルSTTとAivisSpeechを追加する。学習時だけWSL2上でUnslothを使う。**学習とゲームは同時にしない**。個人的な思い出は学習データへ焼き込まず、SillyTavernの設定・Lorebookに置く。

作業は「素のモデルで文字会話を完成 → 実ゲームで計測 → 音声を接続 → データ作成とQLoRA → GGUFを書き出して比較」の順。27B Q4が必ずゲームと共存するとは限らない。モデルファイルのサイズは実際のVRAM占有量ではない。

### 用意するもの

- Windows用Git、Node.jsの現行LTS、NVIDIAドライバー、十分な空きディスク（モデル、学習用重み、書き出しとバックアップを含め数百GBを見込む）。
- 作業例: `D:\AI\MaidAI\{models,koboldcpp,SillyTavern,datasets,exports,backups}`。ドライブ名は適宜変更。
- インストーラー・モデルは下の公式URLから取得。実行ファイルやモデルの出所とライセンスを記録する。
- Windows PowerShellで `nvidia-smi`、`git --version`、`node --version` を確認。空きVRAMはゲームを起動した状態でも確認する。

## 1. 文字会話をローカルで動かす

### 1-1. モデルをダウンロード

[UnslothのQwen3.8-27B GGUF](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/main)から、まず `Qwen3.8-27B-UD-Q4_K_XL.gguf`、ゲーム用候補に `Qwen3.8-27B-UD-Q3_K_XL.gguf` をそれぞれ選ぶ。UIでファイル単位ダウンロードでもよい。Hugging Face CLIを使うなら、PowerShellで次を**一行ずつ**実行する。

```powershell
python -m pip install -U huggingface_hub
hf auth login
hf download unsloth/Qwen3.8-27B-GGUF Qwen3.8-27B-UD-Q4_K_XL.gguf --local-dir D:\AI\MaidAI\models
hf download unsloth/Qwen3.8-27B-GGUF Qwen3.8-27B-UD-Q3_K_XL.gguf --local-dir D:\AI\MaidAI\models
```

`hf auth login` は公開モデルの取得には必須ではないが、アカウントがあるなら利用する。ダウンロード後、ファイルが数十GB級であり、途中までの破損ファイルでないことを確認。モデルがKoboldCppの現行版で読めない場合は、先にKoboldCppを更新する。

### 1-2. KoboldCpp

[公式Releases](https://github.com/LostRuins/koboldcpp/releases)からWindows/NVIDIA CUDA対応版を取得し、`D:\AI\MaidAI\koboldcpp` に置いて起動。Quick LaunchでモデルにQ4を指定、`Use CuBLAS`、RTX 4090を選択。最初は `Context Size = 8192`、GPU Layersは可能なら全層、KV cacheはまず既定値、Flash Attentionは有効（現行版では既定で有効な場合がある）。ポート5001、ローカルホストのみで起動し、設定を保存。ログでモデル読み込み完了とGPUへのオフロードを確認する。ブラウザで `http://127.0.0.1:5001` を開いて日本語の短い往復をテスト。

**ゲーム用プリセット**はQ3、8K contextから作り、余裕があれば16Kに上げる。**通常用**はQ4、8K→16K→必要なら32K。KVの量子化はVRAM不足が出たときにQ8、その後Q4を試し、文脈保持と速度を比較する。`--gpulayers` 等の起動引数はリリースによって変化するので、保存済みGUI設定と現行版ヘルプを優先する。

### 1-3. SillyTavern

GitとNode.js LTSを導入後、PowerShellで実行。Windows管理フォルダーや管理者権限での実行は避ける。

```powershell
cd D:\AI\MaidAI
git clone https://github.com/SillyTavern/SillyTavern -b release
cd .\SillyTavern
.\Start.bat
```

ブラウザで起動したら API Connections → **Text Completion → KoboldCpp**、URLを `http://127.0.0.1:5001` として接続。バージョンによってメニュー表記が異なれば公式の接続ガイドを参照する。まずストリーミングを有効にして一往復。返事に `thinking` や内部タグが混入しないか確認し、モデル指定のchat templateとSillyTavernのフォーマットが二重適用されていないか確認する。

## 2. メイドの人格と記憶

SillyTavernでキャラクターカードを作成する。初期の設定例:

```text
名前: （任意の名前）
役割: さにゃんに仕える専属メイド。通常は自然な日本語の丁寧語で「ご主人様」と呼ぶ。
性格: 思いやりがあり、好奇心旺盛。必要なときは率直に意見を言う。
会話: 返事は会話らしく簡潔。毎回お辞儀や所作を描写しない。知らない出来事や思い出を捏造しない。
ゲーム: Valheim・Factorioの話題に付き合う。画面情報が与えられていないときはゲーム状態を見ているふりをしない。
関係: 親密さは会話の文脈に沿って調整する。成人同士の創作RPは別の任意設定として管理する。
```

最初のメッセージ例: `お帰りなさいませ、ご主人様。今日は何から始めましょうか。`。会話例を3～10件追加し、呼び方・文量・世話の焼き方を示す。個人情報や実際の思い出はLorebookに短い項目として登録し、後から訂正できるようにする。ゲームを実際に観察して反応させるには別途ゲーム連携が必要。バックグラウンドで起動しただけではゲーム画面を認識しない。

最初の評価では同じ10～20個の質問と条件（初対面、雑談、訂正、曖昧な質問、ゲーム中の短いやり取り、長めの会話など）を保存し、設定・モデルを変えるたびに比較する。素のモデルとキャラクターカードだけで十分なら学習を急がない。

## 3. ゲーム併用を実測する

Windows側で `nvidia-smi -l 1` を実行。通常プリセット単体、Factorio＋通常、Valheim＋通常、各ゲーム＋Q3ゲーム用の順に測る。ゲーム起動後・長時間プレイ後・LLM生成中のVRAM使用量、ゲームのフレーム時間、最初の返答までの時間、生成速度を記録する。画質・MOD・解像度で結果は変わる。

VRAMが詰まるときは順に **contextを下げる → Q3に切り替える → KVをQ8/Q4へ → GPUレイヤーを調整**。CPUへの大幅オフロードはFactorioの更新速度に影響しうるので最終手段。Q3で文章が気になる、またはゲームの余裕が足りないなら14B級を別案として再評価する。「Q4は常にゲーム用」と決めつけない。

## 4. 音声を後付けする

### 4-1. 読み上げ（TTS）

[AivisSpeech](https://github.com/Aivis-Project/AivisSpeech)と[AivisSpeech Engine](https://github.com/Aivis-Project/AivisSpeech-Engine)を公式手順で入れ、まず単独で日本語合成を成功させる。EngineのVOICEVOX互換APIは通常 `http://127.0.0.1:10101`。SillyTavernのTTS拡張で**現行版にVOICEVOX互換の接続先があるか確認**し、そのURLと話者IDを設定する。互換プロバイダーがない場合はAivisSpeech対応の拡張・ブリッジを別途検証する。標準の「OpenAI互換TTS」欄にEngineのURLを入れるだけで動くとは想定しない。まずCPUモードで声と遅延を計測し、必要な場合だけGPUに変更する。モデルによって利用規約・声の使用条件を確認。

### 4-2. 音声認識（STT）

SillyTavernのExtensions → Download Extensions & Assetsから Speech Recognition を導入。最初はブラウザの対応手段を使い、精度・プライバシー要件が合うか確認。完全ローカルが必要ならWhisper系ローカルサービスを用意して、**そのサービスと現在のSillyTavern拡張が直接接続できる方式を確認してから**統合する。古い SillyTavern Extras の `whisper-stt` は公式文書で deprecated 扱いのため、新規構築の既定手順にしない。音声の自動送信やTTSの自動再生はゲーム中の誤作動を防ぐため最初はオフにして確認。

## 5. WSL2とUnslothで学習する

学習時はKoboldCpp・ゲームなどGPU負荷のあるアプリを閉じる。管理者PowerShellで `wsl --install -d Ubuntu-24.04`、再起動と初期ユーザー作成を済ませる。すでにUbuntuがあるなら `wsl --list --verbose` でWSL2を確認。Windows側のNVIDIAドライバーを更新し、Ubuntu側では `nvidia-smi` でGPUを確認。WSL内へ別のLinux GPUドライバーをむやみに入れない。

Unslothの[公式Qwen3.8学習ガイド](https://unsloth.ai/docs/models/qwen3.8/train)に従い、[Windows/WSL導入ページ](https://unsloth.ai/docs/get-started/install/windows-installation)の現行手順でインストール。WSL手動導入の公式コマンドは `curl -fsSL https://unsloth.ai/install.sh | sh` だが、URLの内容を確認して実行する。導入後、Qwen3.8の `unsloth/Qwen3.8-27B-unsloth-bnb-4bit` を選択。公式は24GBでQLoRA可能と案内するが設定次第でOOMになる。

### 5-1. データの設計

まず100～500例の質の高い会話を作る。一般会話、メイドらしい応答、ゲームの短い会話、場面に応じた親密さをバランスよく含める。必要な成人向けRPは別ファイルに分け、成人同士の合意ある場面だけを扱う。同じ言い回しの大量複製、常に長い地の文、毎回「ご主人様」で始まる偏りを避ける。10%程度を評価専用に確保し学習に流用しない。

作成・編集しやすい原稿は次のようなJSONL（1行1会話）。これは**中間形式**で、学習前に公式トークナイザーのchat templateで `text` 列へ変換する。

```json
{"messages":[{"role":"system","content":"あなたはさにゃんに仕える専属メイド。自然な日本語で会話する。"},{"role":"user","content":"ただいま。今日はFactorioで鉄板が足りなくて疲れたよ"},{"role":"assistant","content":"お帰りなさいませ、ご主人様。鉄板不足は工場全体に響きますね。まず炉の稼働率と鉱石の搬入、どちらが詰まっているか見てみましょうか。"}]}
```

学習用変換の例（WSLで実行、Transformersを導入済みとする）。パスとモデルIDは手元の配置に合わせる。

```python
import json
from transformers import AutoTokenizer

model_id = "unsloth/Qwen3.8-27B-unsloth-bnb-4bit"
tok = AutoTokenizer.from_pretrained(model_id)
with open("maid_messages.jsonl", encoding="utf-8") as src, open("train.jsonl", "w", encoding="utf-8") as dst:
    for line in src:
        messages = json.loads(line)["messages"]
        rendered = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        dst.write(json.dumps({"text": rendered}, ensure_ascii=False) + "\n")
```

学習と推論でchat template・EOS・thinking設定を一致させる。思考過程を含まないRPを狙うなら、実際にモデルがどういう制御方法を受け付けるか公式モデルカード・Unslothの現行手順を確認し、訓練と推論で同じ条件にする。

### 5-2. 小さくQLoRAを回す

Unslothの公式ガイドにある **SFT recipeをコピーして開始**。`max_seq_length=2048`、4-bit、batch=1、gradient accumulation=4、LoRA `r=16`、`offload_embedding=True`、language/attention/MLPのみ学習・vision層は無効、少ないstepsから。データには上記の `text` 列を使う。OOMならまず長さを短くし、バッチ1とgradient checkpointingを維持。lossだけで決めず、未学習の固定質問セットで「口調・短さ・日本語・設定遵守・繰り返し」を比較する。気に入ったadapter、データ、設定、seed、学習ログを保存する。

### 5-3. GGUFを書き出す

公式の `model.save_pretrained_gguf("maid-qwen38-q4", tokenizer, quantization_method="q4_k_m")` でQ4を作り、アダプターのみも `model.save_pretrained(...)` で別保存。Q3の具体的な `quantization_method` はその時点のUnsloth対応一覧を確認してから指定する。未確認の `UD-Q3_K_XL` を保存メソッドへそのまま渡さない。必要ならマージ済み重みを出力し、対応したllama.cpp量子化ツールでQ3を作る。書き出しは一時的に大きなディスク容量とRAMを使う。公開用Hubへはアップロードせずローカルへ保存する。

生成されたGGUFをKoboldCppへ読み込み、元のGGUFと**同じキャラクターカード・同じ質問・同じ生成設定**で比較。LoRAの効果が薄い、設定依存が大きい、反復が増えた場合はデータを直して再学習する。元モデルと前回のadapterを削除せず、戻せる状態を保つ。

## 6. 完成判定と運用

- [ ] Q4で日本語文字会話が自然に続く。モデル名・量子化・chat templateを記録。
- [ ] FactorioとValheimでQ4/Q3を測り、長時間プレイでフレーム時間とVRAMに余裕がある設定を保存。
- [ ] メイドカードとLorebookをバックアップ。知らないゲーム状況や思い出を捏造しない。
- [ ] 音声はTTS単独、STT単独、連携の順に確認。CPU/GPU使用量と遅延を比較。
- [ ] 学習前後を固定プロンプトで比較し、改善した版だけを採用。
- [ ] SillyTavernデータ、datasets、adapter、学習設定、GGUFをバージョンごとにバックアップ。

### つまずいたとき

| 症状 | 最初に確認すること |
|---|---|
| KoboldCppがモデルを読めない | 現行版への更新、GGUFの完全性、モデル形式への対応 |
| 接続できない | KoboldCppの5001起動、SillyTavernのKoboldCpp選択、localhost URL |
| 返答にタグや思考が出る | chat template、thinking設定、プロンプトの二重適用 |
| ゲームがカクつく | VRAM実測、Q3/8K、KV量子化、GPUレイヤー数 |
| 学習がOOM | 他GPUプロセス終了、max_seq_length低下、batch=1、embedding offload |
| 学習後に話し方が単調 | 学習データの重複・偏り、steps過多、評価セットとの比較 |
| 声が出ない | Engine単独合成、ポート10101、SillyTavern側の対応プロバイダーと話者ID |

## 公式参照先

- [Qwen公式モデルカード](https://huggingface.co/Qwen/Qwen3.8-27B)
- [Unsloth GGUFとファイル一覧](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/main)
- [Unsloth: Qwen3.8学習・エクスポート](https://unsloth.ai/docs/models/qwen3.8/train)
- [KoboldCpp公式](https://github.com/LostRuins/koboldcpp) / [設定Wiki](https://github.com/LostRuins/koboldcpp/wiki)
- [SillyTavern Windows導入](https://docs.sillytavern.app/installation/windows/) / [KoboldCpp接続](https://docs.sillytavern.app/usage/api-connections/koboldcpp/) / [STT](https://docs.sillytavern.app/extensions/speech-recognition/) / [TTS](https://docs.sillytavern.app/extensions/tts/)
- [Microsoft: WSL導入](https://learn.microsoft.com/windows/wsl/install) / [WSL GPU](https://learn.microsoft.com/windows/wsl/tutorials/gpu-compute)
- [AivisSpeech Engine公式](https://github.com/Aivis-Project/AivisSpeech-Engine)
