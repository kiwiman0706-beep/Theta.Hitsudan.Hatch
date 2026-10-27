"""操作ログ。1日1ファイルの JSON Lines（1行1イベント）で追記する。

診療内容を含むので、保存先は院内PCのローカルに限り、バックアップと保存期間は院内規程に合わせること。
"""
from __future__ import annotations

import csv
import io
import json
import threading
from datetime import datetime
from pathlib import Path

from config import CONFIG

_lock = threading.Lock()


def _dir() -> Path:
    d = Path(CONFIG["log_dir"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def write(event: str, **fields) -> dict:
    now = datetime.now().astimezone()
    rec = {"ts": now.isoformat(timespec="seconds"), "event": event, **fields}
    with _lock, open(_dir() / f"{now:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def read(day: str) -> list[dict]:
    path = _dir() / f"{day}.jsonl"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


CSV_COLUMNS = ["ts", "event", "encounter", "msg_id", "lang", "asr_raw", "source_ja", "translation", "back_translation", "reply", "detail"]


def to_csv(day: str) -> str:
    """Excel / SmoothCSV で開けるよう BOM 付き UTF-8 の CSV にする。"""
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for rec in read(day):
        w.writerow(rec)
    return buf.getvalue()
