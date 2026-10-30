# 筆談・翻訳表示システム（Theta.Hitsudan.Hatch）

診察室で医師が話した言葉を音声認識し、

- **外国語の患者さん** → 翻訳して
- **耳の不自由な患者さん** → 日本語のまま

患者さんの手元の画面（電子ペーパー端末 / タブレット）に大きな文字で表示します。

**音声認識や翻訳の結果は、医師が確認してから送るまで患者さんには出ません。**
翻訳は「訳文を日本語に戻した文」で意味を確認できます。操作はすべてログに残ります。

設計の考え方と機器選定は [docs/design.md](docs/design.md) を参照してください。

```
app/
  server.py          サーバー本体（確認フロー・送信・ログ）
  asr.py             音声認識（faster-whisper、PC内で処理）
  start.py           2ウインドウ起動（医師用・患者用）
  translator.py      翻訳と逆翻訳（Gemini API / Claude API）
  render.py          患者側画面の画像化（電子ペーパー用）
  serial_display.py  USB接続の電子ペーパー端末への送信
  logstore.py        ログ（JSON Lines / CSV出力）
  languages.py       対応言語・患者の返答ボタン文言
  static/doctor.html 医師用画面
  static/patient.html 患者用画面（タブレット等のブラウザ用）
firmware/m5papers3/  M5PaperS3 用ファームウェア（Arduino）
tools/device_emulator.py  実機なしで電子ペーパー送信を試すエミュレータ
tests/test_flow.py   確認フローのテスト
```

## 1. 準備

### 1-1. Python ライブラリ

Python 3.12 は導入済みとのことなので、プロジェクト用の仮想環境を作って入れます。

**Windows（PowerShell）**
```powershell
cd Theta.Hitsudan.Hatch
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r app\requirements.txt
```

**Mac（ターミナル）**
```bash
cd Theta.Hitsudan.Hatch
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt
```

NVIDIA GPU で音声認識を速くしたい場合（Windows）は、faster-whisper の説明に従って CUDA 12 用の cuBLAS / cuDNN を入れてください（`pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` が手軽です）。GPU がなければ CPU で動きます。

### 1-2. 翻訳用の API キー（Gemini）

[Google AI Studio](https://aistudio.google.com/apikey) で API キーを作り、環境変数 `GEMINI_API_KEY` に設定します。

```powershell
# Windows（ユーザー環境変数に保存。新しく開いたターミナルから有効）
setx GEMINI_API_KEY "AIza..."
```
```bash
# Mac（~/.zshrc に追記）
echo 'export GEMINI_API_KEY="AIza..."' >> ~/.zshrc && source ~/.zshrc
```

> **重要（個人情報）**: Gemini API の **無料枠** では、送った内容が Google のサービス改善に使われることがあります。
> 診察で使うときは、AI Studio でそのプロジェクトに **請求（Billing）を設定した有料枠** にしてください。有料枠では送信内容は学習等に使われません（最新の利用規約で確認してください）。
> テストは架空の文で行ってください。

- モデルは既定で `gemini-3.8-flash`。変更は `config.local.json` の `gemini_model` で。
- Claude を使う場合は `"translator": "claude"` にして `ANTHROPIC_API_KEY` を設定。
- 筆談（日本語のみ）だけならキーは不要です（キーがなくても翻訳以外は動きます）。

### 1-3. 設定（任意）

`config.local.example.json` を `config.local.json` にコピーして編集します。主な項目:

| 項目 | 説明 |
|---|---|
| `asr_model` | `large-v3-turbo`（GPU向け・高精度）/ `medium` / `small`（CPU向け・速い） |
| `asr_initial_prompt` | よく使う医療用語・薬剤名を並べておくと認識精度が上がります |
| `serial_port` | 電子ペーパー端末のポート。Windows は `COM5` など、Mac は `/dev/cu.usbmodem…` |
| `save_audio` | 録音を残すか（既定は残さない） |
| `show_japanese_under_translation` | 翻訳の下に日本語原文を小さく出すか（同席の家族・通訳向け） |
| `font_max_px` / `font_min_px` | 患者画面の文字サイズの上限・下限 |

### 1-4. フォント（多言語で使う場合）

日本語・英語は OS 標準のフォントで表示できます。中国語・韓国語・タイ語・ベトナム語・ネパール語もきれいに出したい場合は、
[Google Fonts](https://fonts.google.com/noto) から次の Bold を入手して `fonts/` フォルダに置いてください。

`NotoSansJP-Bold.ttf` / `NotoSans-Bold.ttf` / `NotoSansSC-Bold.ttf` / `NotoSansKR-Bold.ttf` / `NotoSansThai-Bold.ttf` / `NotoSansDevanagari-Bold.ttf`

## 2. 起動と使い方

### 2ウインドウで起動（このPCだけで使う）

- Windows: `start_windows.bat` をダブルクリック
- Mac: `start_mac.command` をダブルクリック（初回は右クリック→「開く」）
- またはターミナルで `cd app` → `python start.py`

Edge か Chrome が「アドレスバーのない窓」で2つ開きます。

| ウインドウ | 内容 |
|---|---|
| 医師用（左） | 録音・確認・送信の操作画面。マイクの許可は自動 |
| 患者用（右） | 確認して送った文だけが大きく出る。ダブルクリックで全画面 |

- 患者用ウインドウは患者さんの方へ向けたノートPCの画面や、手元の小さなモニターに移動して使います。位置と大きさは `config.local.json` の `patient_window`（x, y, 幅, 高さ）、最初から全画面にするなら `"patient_fullscreen": true`。
- **医師用ウインドウを閉じると全部終了** します。
- 次の段階で外部の表示機器（電子ペーパー端末など）を足しても、操作は同じです（3章）。

### タブレットにも表示したい場合

`config.local.json` に `"host": "0.0.0.0"` を設定して起動し、同じ Wi-Fi のタブレットで `http://<医師PCのIPアドレス>:8000/patient` を開きます。
IP は Windows なら `ipconfig`、Mac なら `ipconfig getifaddr en0` で確認できます。初回は Windows のファイアウォールの許可を求められます（プライベートネットワークのみ許可）。

### 診察での操作

1. 上部で **患者の言語** を選ぶ（耳の不自由な方は「日本語（翻訳なし・筆談）」）。受付番号は任意。
2. **録音開始** を押して話し、もう一度押して止める（または **F8 を押している間だけ録音**。USBフットスイッチに F8 を割り当てると手を使わずに済みます）。定型文ボタンやテキスト入力も使えます。
3. 認識された日本語を確認し、誤りがあれば直す。
4. 翻訳する場合は **翻訳して確認する**。「日本語に戻した文」を読んで、意味が合っているか確認する。
5. 下のプレビュー（患者さんに出る画面そのもの）を見て **患者に送る**。
6. 患者さんが「わかりました / もう一度 / 質問があります」を押すと、医師画面に通知が出てログに残ります。
7. 診察が終わったら **患者の画面を消す**。

### ログ

- `logs/2026-10-27.jsonl` のように 1日1ファイル。音声認識の生の結果、修正後の日本語、訳文、逆翻訳、送信、患者の返答がすべて時刻付きで残ります。
- 医師画面の「今日のログをCSVで保存」で Excel / SmoothCSV で開ける CSV を取り出せます。
- 診療情報を含むので、PCのディスク暗号化（BitLocker / FileVault）と、院内規程に沿った保存期間の管理をしてください。

## 3. 電子ペーパー端末（M5PaperS3）

1. Arduino IDE 2 をインストール（Windows: `winget install ArduinoSA.IDE.stable` / Mac: `brew install --cask arduino-ide`）。
2. ボードマネージャで「esp32 by Espressif」、ライブラリマネージャで「M5Unified」「M5GFX」を入れる。
3. `firmware/m5papers3/m5papers3.ino` を開き、ボード「M5PaperS3」（無ければ ESP32S3 Dev Module）、**USB CDC On Boot: Enabled**、**PSRAM: OPI PSRAM** にして書き込む。
4. USB で PC につないだまま、`config.local.json` の `serial_port` にポート名を設定してサーバーを再起動。医師画面の「電子ペーパー」が緑になれば接続完了です。

実機がなくても試せます:

```bash
python tools/device_emulator.py          # 別ターミナルで起動
# config.local.json に "serial_port": "socket://127.0.0.1:7777" を設定してサーバーを起動
```
送った画面が `tools/emulator_screen.png` に保存され、Enter で「わかりました」を押したことになります。

## 4. テスト

```bash
pip install pytest httpx
python -m pytest tests
```
翻訳 API・音声認識・実機を使わずに、「確認していない訳文は送れない」「ログが残る」「端末にフレームが届く」ことを確認します。
