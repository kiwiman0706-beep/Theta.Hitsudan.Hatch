"""設定。既定値 → config.local.json → 環境変数 の順に上書きする。"""
from __future__ import annotations

import json
import os
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    # --- サーバー ---
    "host": "0.0.0.0",          # 患者用タブレットからLAN経由で見る場合は 0.0.0.0
    "port": 8000,
    # --- 音声認識 (faster-whisper, ローカル実行) ---
    "asr_enabled": True,
    "asr_model": "large-v3-turbo",   # CPUのみなら "small" や "medium" を推奨
    "asr_device": "auto",            # "cuda" / "cpu" / "auto"
    "asr_compute_type": "default",   # GPU: "float16", CPU: "int8" など
    # 医療用語の認識精度を上げるためのヒント（固有名詞・薬剤名などを並べる）
    "asr_initial_prompt": "これは病院の診察室での医師の説明です。血圧、採血、点滴、内服薬、副作用、アレルギー、レントゲン、CT、MRI。",
    "save_audio": False,             # 音声ファイルを残すか（個人情報なので既定は残さない）
    # --- 翻訳 (Claude API) ---
    "translator": "claude",          # "claude" / "none"（翻訳なし: 手入力のみ）
    "claude_model": "claude-opus-5-5",
    "claude_effort": "medium",
    # --- 表示 ---
    "display_width": 960,            # M5PaperS3 の横置き解像度
    "display_height": 540,
    "font_max_px": 96,
    "font_min_px": 36,
    "show_japanese_under_translation": True,  # 翻訳表示の下に小さく日本語原文も出す
    # フォント: 言語コード → フォントファイル候補（先頭から存在するものを使う）
    "fonts": {},
    # --- シリアル (M5PaperS3 などのUSB接続端末) ---
    "serial_port": "",               # 例: "COM5" / "/dev/cu.usbmodem1101"。空なら無効
    "serial_baud": 921600,
    # --- ログ ---
    "log_dir": str(ROOT / "logs"),
    "audio_dir": str(ROOT / "audio"),
}

# OSごとの既定フォント候補。多言語を出すなら Noto Sans 系を fonts/ に置くのが確実。
_SYS = platform.system()
if _SYS == "Windows":
    _JA = ["C:/Windows/Fonts/BIZ-UDGothicB.ttc", "C:/Windows/Fonts/YuGothB.ttc", "C:/Windows/Fonts/meiryob.ttc", "C:/Windows/Fonts/meiryo.ttc"]
    _LATIN = ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"]
    _ZH = ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc"]
    _KO = ["C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf"]
    _TH = ["C:/Windows/Fonts/leelawdb.ttf", "C:/Windows/Fonts/tahomabd.ttf"]
elif _SYS == "Darwin":
    _JA = ["/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc"]
    _LATIN = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"]
    _ZH = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc"]
    _KO = ["/System/Library/Fonts/AppleSDGothicNeo.ttc"]
    _TH = ["/System/Library/Fonts/Supplemental/Thonburi.ttc", "/System/Library/Fonts/Thonburi.ttc"]
else:
    _JA = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"]
    _LATIN = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    _ZH = _JA
    _KO = _JA
    _TH = ["/usr/share/fonts/truetype/noto/NotoSansThai-Bold.ttf"]

_LOCAL = [str(ROOT / "fonts" / n) for n in ("NotoSansJP-Bold.ttf", "NotoSansCJK-Bold.ttc")]
DEFAULT_FONTS = {
    "ja": _LOCAL + _JA,
    "zh": [str(ROOT / "fonts" / "NotoSansSC-Bold.ttf")] + _ZH + _JA,
    "ko": [str(ROOT / "fonts" / "NotoSansKR-Bold.ttf")] + _KO + _JA,
    "th": [str(ROOT / "fonts" / "NotoSansThai-Bold.ttf")] + _TH,
    # デーヴァナーガリー(ネパール語)。Pillow が raqm 付きでないと字形が崩れる
    "deva": [str(ROOT / "fonts" / "NotoSansDevanagari-Bold.ttf"), "C:/Windows/Fonts/NirmalaB.ttf",
             "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
             "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf"],
    # ラテン文字系(英・西・葡・越・タガログ・インドネシア等)。ベトナム語の声調記号も出せるフォントを。
    "latin": [str(ROOT / "fonts" / "NotoSans-Bold.ttf")] + _LATIN + _JA,
}


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    local = ROOT / "config.local.json"
    if local.exists():
        cfg.update(json.loads(local.read_text(encoding="utf-8")))
    for key, default in DEFAULTS.items():
        env = os.environ.get("HITSUDAN_" + key.upper())
        if env is None:
            continue
        if isinstance(default, bool):
            cfg[key] = env.lower() in ("1", "true", "yes", "on")
        elif isinstance(default, int):
            cfg[key] = int(env)
        elif isinstance(default, (str,)):
            cfg[key] = env
    fonts = dict(DEFAULT_FONTS)
    fonts.update(cfg.get("fonts") or {})
    cfg["fonts"] = fonts
    return cfg


CONFIG = load()
