"""音声認識（faster-whisper をPC内で実行。音声を外部に送らない）。"""
from __future__ import annotations

import threading
from pathlib import Path

from config import CONFIG


class ASRUnavailable(RuntimeError):
    pass


class ASR:
    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()
        self.error: str | None = None

    def _load(self):
        if self._model is not None:
            return self._model
        if not CONFIG["asr_enabled"]:
            raise ASRUnavailable("音声認識は無効です（asr_enabled=false）。テキストを直接入力してください")
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise ASRUnavailable("faster-whisper が入っていません: pip install faster-whisper") from e
        device = CONFIG["asr_device"]
        compute = CONFIG["asr_compute_type"]
        if compute == "default":
            compute = "int8" if device == "cpu" else "default"
        self._model = WhisperModel(CONFIG["asr_model"], device=device, compute_type=compute)
        return self._model

    def preload(self) -> None:
        """起動時に裏でモデルを読み込んでおく（初回の待ち時間を減らす）。"""
        try:
            with self._lock:
                self._load()
        except Exception as e:  # noqa: BLE001 - 起動は止めず、画面に理由を出す
            self.error = str(e)

    def transcribe(self, audio_path: Path) -> str:
        with self._lock:
            model = self._load()
            segments, _info = model.transcribe(
                str(audio_path),
                language="ja",
                beam_size=5,
                vad_filter=True,
                initial_prompt=CONFIG["asr_initial_prompt"] or None,
                condition_on_previous_text=False,
            )
            return "".join(s.text for s in segments).strip()
