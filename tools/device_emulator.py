"""電子ペーパー端末のエミュレータ（実機なしで送信テストをするため）。

TCPで待ち受け、受け取った画面を PNG に保存して "OK" を返す。
Enter を押すと「わかりました」ボタンを押したことにする（TOUCH を送る）。

使い方:
    python tools/device_emulator.py            # 127.0.0.1:7777 で待ち受け
    サーバー側は config.local.json に {"serial_port": "socket://127.0.0.1:7777"}
"""
from __future__ import annotations

import socket
import struct
import sys
import threading
import zlib
from pathlib import Path

from PIL import Image

HOST, PORT = "127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 7777
OUT = Path(__file__).resolve().parent / "emulator_screen.png"


def recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def serve(conn: socket.socket) -> None:
    conn.sendall(b"READY\n")
    while True:
        # "HTDN" を探す
        window = b""
        while window != b"HTDN":
            window = (window + recv_exact(conn, 1))[-4:]
        kind, w, h, length = struct.unpack("<BHHI", recv_exact(conn, 9))
        payload = recv_exact(conn, length)
        (crc,) = struct.unpack("<I", recv_exact(conn, 4))
        if crc != zlib.crc32(payload) & 0xFFFFFFFF:
            conn.sendall(b"ERR crc\n")
            continue
        if kind == 1:
            img = Image.frombytes("1", (w, h), payload)
            # 1=黒 で送られてくるので反転して保存
            img.convert("L").point(lambda v: 255 - v).save(OUT)
            print(f"画面を受信 {w}x{h} → {OUT}")
        else:
            print("画面クリア")
        conn.sendall(b"OK\n")


def main() -> None:
    srv = socket.create_server((HOST, PORT))
    print(f"待ち受け中 socket://{HOST}:{PORT}  (Enter で『わかりました』を押す)")
    conn, _ = srv.accept()
    print("サーバーが接続しました")
    threading.Thread(target=serve, args=(conn,), daemon=True).start()
    for _ in sys.stdin:
        conn.sendall(b"TOUCH 170 480\n")  # 960x540 画面の左下ボタン付近


if __name__ == "__main__":
    main()
