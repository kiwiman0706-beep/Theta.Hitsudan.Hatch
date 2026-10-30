"""2ウインドウで起動する: 医師用（操作）と患者用（表示）。

サーバーを起動し、Edge か Chrome を「アプリ表示（アドレスバーなし）」で2つ開く。
医師用ウインドウを閉じると、患者用ウインドウとサーバーも終了する。

    python start.py
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from config import CONFIG, ROOT

PROFILE_DIR = ROOT / ".browser"

CANDIDATES = {
    "Windows": [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ],
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ],
    "Linux": ["google-chrome", "chromium", "chromium-browser", "microsoft-edge"],
}


def find_browser() -> str | None:
    if CONFIG["browser"]:
        return CONFIG["browser"]
    for c in CANDIDATES.get(platform.system(), []):
        path = os.path.expandvars(c)
        if Path(path).exists():
            return path
        found = shutil.which(c)
        if found:
            return found
    return None


def open_window(browser: str, url: str, profile: str, x: int, y: int, w: int, h: int, extra: list[str]) -> subprocess.Popen:
    # ウインドウごとに別のプロファイルにすると、それぞれ独立したプロセスになり
    # 位置・大きさの指定が効き、閉じたことも検知できる
    args = [
        browser,
        f"--app={url}",
        f"--user-data-dir={PROFILE_DIR / profile}",
        f"--window-position={x},{y}",
        f"--window-size={w},{h}",
        "--no-first-run",
        "--no-default-browser-check",
        *extra,
    ]
    return subprocess.Popen(args)


def wait_server(url: str, timeout: float = 30) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url + "/api/state", timeout=1)
            return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError("サーバーが起動しませんでした")


def main() -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    import server  # noqa: F401 - 読み込み時にアプリを作る

    host = CONFIG["host"]
    url = f"http://127.0.0.1:{CONFIG['port']}"
    srv = uvicorn.Server(uvicorn.Config(server.app, host=host, port=CONFIG["port"], log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    wait_server(url)
    print(f"サーバー起動: {url}")

    browser = find_browser()
    if not browser:
        print("Edge / Chrome が見つからないので既定のブラウザで開きます（ウインドウ配置は手動で）")
        webbrowser.open(url + "/")
        webbrowser.open(url + "/patient")
        print("終了するにはこの画面で Ctrl+C を押してください")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    px, py, pw, ph = CONFIG["patient_window"]
    patient_extra = ["--start-fullscreen"] if CONFIG["patient_fullscreen"] else []
    # 医師用はマイクを使う。専用プロファイル・ローカル画面だけなので許可ダイアログを省く
    doctor = open_window(browser, url + "/", "doctor", 40, 40, 940, 900, ["--use-fake-ui-for-media-stream"])
    time.sleep(1.0)
    patient = open_window(browser, url + "/patient", "patient", px, py, pw, ph, patient_extra)
    print("医師用ウインドウを閉じると終了します（Ctrl+C でも終了）")

    try:
        doctor.wait()
    except KeyboardInterrupt:
        doctor.terminate()
    patient.terminate()
    srv.should_exit = True
    time.sleep(0.5)


if __name__ == "__main__":
    main()
