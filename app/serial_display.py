"""USBシリアル接続の電子ペーパー端末（M5PaperS3 など）への送信。

フレーム形式（PC → 端末、数値はすべてリトルエンディアン）:
    "HTDN"(4) | 種別 u8 | 幅 u16 | 高さ u16 | 長さ u32 | データ | CRC32 u32
    種別 1 = 1bpp画像（行ごとMSB先、1=黒）, 2 = 画面クリア（データ長0）
端末 → PC は1行ずつのテキスト:
    "READY" / "OK" / "ERR 理由" / "TOUCH x y"
BLE版も同じフレームを分割して流す想定（docs/design.md 参照）。
"""
from __future__ import annotations

import logging
import struct
import threading
import time
import zlib
from typing import Callable

log = logging.getLogger("serial_display")

MAGIC = b"HTDN"
TYPE_IMAGE = 1
TYPE_CLEAR = 2


def build_frame(kind: int, width: int, height: int, payload: bytes) -> bytes:
    head = MAGIC + struct.pack("<BHHI", kind, width, height, len(payload))
    return head + payload + struct.pack("<I", zlib.crc32(payload) & 0xFFFFFFFF)


class SerialDisplay:
    def __init__(self, port: str, baud: int, on_touch: Callable[[int, int], None], on_status: Callable[[str], None]):
        self.port = port
        self.baud = baud
        self.on_touch = on_touch
        self.on_status = on_status
        self._ser = None
        self._write_lock = threading.Lock()
        self._ack = threading.Event()
        self._last_reply = ""
        self.connected = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        import serial  # pyserial

        while True:
            try:
                self._ser = serial.serial_for_url(self.port, self.baud, timeout=0.5)
                self.connected = True
                self.on_status(f"端末接続: {self.port}")
                while True:
                    line = self._ser.readline().decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    if line.startswith("TOUCH "):
                        _, x, y = line.split()
                        self.on_touch(int(x), int(y))
                    elif line in ("OK",) or line.startswith("ERR"):
                        self._last_reply = line
                        self._ack.set()
                    elif line == "READY":
                        self.on_status("端末 READY")
                    else:
                        log.info("device: %s", line)
            except Exception as e:  # noqa: BLE001 - 抜き差しに耐えるため再接続を続ける
                if self.connected:
                    self.on_status(f"端末切断: {e}")
                self.connected = False
                try:
                    if self._ser:
                        self._ser.close()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(2)

    def send(self, frame: bytes, timeout: float = 8.0) -> str:
        """フレームを送り、端末の OK/ERR を待つ。戻り値は端末の返事。"""
        if not self.connected or not self._ser:
            raise ConnectionError("端末が接続されていません")
        with self._write_lock:
            self._ack.clear()
            self._ser.write(frame)
            self._ser.flush()
            if not self._ack.wait(timeout):
                raise TimeoutError("端末から応答がありません")
            if self._last_reply != "OK":
                raise ConnectionError(f"端末エラー: {self._last_reply}")
            return self._last_reply
