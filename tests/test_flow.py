"""確認フローの検査。翻訳APIと音声認識は使わず、電子ペーパー端末はエミュレータで代用する。

    python -m pytest tests   （または python tests/test_flow.py）
"""
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

PORT = 17777
os.environ["HITSUDAN_LOG_DIR"] = tempfile.mkdtemp()
os.environ["HITSUDAN_ASR_ENABLED"] = "false"
os.environ["HITSUDAN_TRANSLATOR"] = "none"
os.environ["HITSUDAN_SERIAL_PORT"] = f"socket://127.0.0.1:{PORT}"

received = []


def fake_device():
    srv = socket.create_server(("127.0.0.1", PORT))
    conn, _ = srv.accept()
    conn.sendall(b"READY\n")
    buf = b""
    while True:
        data = conn.recv(65536)
        if not data:
            return
        buf += data
        while True:
            i = buf.find(b"HTDN")
            if i < 0 or len(buf) < i + 13:
                break
            kind, w, h, n = struct.unpack("<BHHI", buf[i + 4:i + 13])
            if len(buf) < i + 13 + n + 4:
                break
            payload = buf[i + 13:i + 13 + n]
            (crc,) = struct.unpack("<I", buf[i + 13 + n:i + 17 + n])
            buf = buf[i + 17 + n:]
            ok = crc == zlib.crc32(payload) & 0xFFFFFFFF
            received.append((kind, w, h, len(payload), ok))
            conn.sendall(b"OK\n" if ok else b"ERR crc\n")
            if kind == 1:
                conn.sendall(b"TOUCH 170 480\n")  # 「わかりました」ボタン


threading.Thread(target=fake_device, daemon=True).start()
time.sleep(0.2)

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import logstore  # noqa: E402


class FakeTranslator:
    enabled = True

    def status(self):
        return "OK（fake）"

    def translate(self, ja, lang):
        return f"[{lang}] {ja}"

    def back_translate(self, text, lang):
        return "（逆翻訳）" + text.split("] ", 1)[-1]


server.translator = FakeTranslator()


def wait_connected(client):
    for _ in range(50):
        if "接続" in client.get("/api/state").json()["serial"]:
            return
        time.sleep(0.1)
    raise AssertionError("emulator not connected")


def test_flow():
    with TestClient(server.app) as c:
        wait_connected(c)
        c.post("/api/encounter", json={"label": "0123"})

        # 筆談モード: 確認した日本語がそのまま送られる
        m = c.post("/api/message", json={"lang": "ja", "text": "血液検査をします。"}).json()
        r = c.post(f"/api/message/{m['id']}/send", json={"lang": "ja", "source_ja": "血液検査をします。"})
        assert r.status_code == 200, r.text
        assert r.json()["delivered"] == ["eink"]

        # 翻訳モード: 翻訳前は送れない
        m = c.post("/api/message", json={"lang": "en", "text": "明日来てください"}).json()
        r = c.post(f"/api/message/{m['id']}/send", json={"lang": "en", "source_ja": "明日来てください", "translation": "x"})
        assert r.status_code == 409

        m = c.post(f"/api/message/{m['id']}/translate", json={"source_ja": "明日来てください"}).json()
        assert m["back_translation"] == "（逆翻訳）明日来てください"

        # 確認後に訳文を書き換えたものは送れない
        r = c.post(f"/api/message/{m['id']}/send", json={"lang": "en", "source_ja": "明日来てください", "translation": "tampered"})
        assert r.status_code == 409
        # 確認後に日本語を書き換えたものも送れない
        r = c.post(f"/api/message/{m['id']}/send", json={"lang": "en", "source_ja": "今日来てください", "translation": m["translation"]})
        assert r.status_code == 409
        # 言語を切り替えたら確認はやり直し
        r = c.post(f"/api/message/{m['id']}/send", json={"lang": "ko", "source_ja": "明日来てください", "translation": m["translation"]})
        assert r.status_code == 409

        m = c.post(f"/api/message/{m['id']}/translate", json={"source_ja": "明日来てください", "lang": "en"}).json()
        r = c.post(f"/api/message/{m['id']}/send", json={"lang": "en", "source_ja": "明日来てください", "translation": m["translation"]})
        assert r.status_code == 200, r.text

        assert c.post("/api/clear").status_code == 200
        time.sleep(0.3)

        day = time.strftime("%Y-%m-%d")
        events = [e["event"] for e in logstore.read(day)]
        assert events.count("send") == 2
        assert "patient_reply" in events
        assert "translate" in events
        assert c.get(f"/api/logs/{day}.csv").text.startswith("﻿ts,event")

    assert [k for k, *_ in received] == [1, 1, 2]
    assert all(ok for *_, ok in received)
    assert received[0][1:4] == (960, 540, 64800)


if __name__ == "__main__":
    test_flow()
    print("OK")
