#!/bin/bash
# ダブルクリックで医師用・患者用の2ウインドウを起動
cd "$(dirname "$0")"
ROOT="$(pwd)"
if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY=python3.12; fi
cd app
"$PY" start.py
