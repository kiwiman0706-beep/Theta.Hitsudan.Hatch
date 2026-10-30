"""筆談・翻訳表示サーバー。

流れ: 録音 → 音声認識(下書き) → 医師が日本語を修正・確定
      → [翻訳モード] 翻訳 → 逆翻訳(日本語) を医師が確認
      → 「患者に送る」で初めて患者側に表示
未確認の文が患者側に出ないよう、送信時にサーバー側でも
「確認された訳文と送ろうとしている訳文が一致するか」を検査する。

起動: python server.py   （医師用 http://localhost:8000/  患者用 http://<PCのIP>:8000/patient）
"""
from __future__ import annotations

import asyncio
import io
import logging
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

import logstore
import render
from asr import ASR, ASRUnavailable
from config import CONFIG
from languages import LANGUAGES, REPLY_JA, reply_labels
from serial_display import TYPE_CLEAR, TYPE_IMAGE, SerialDisplay, build_frame
from translator import TranslationError, Translator

logging.basicConfig(level=logging.INFO)
STATIC = Path(__file__).parent / "static"

asr = ASR()
translator = Translator()

# ---- 状態（1診察室1台を想定し、メモリ上に持つ） ----
state = {
    "encounter": "",          # 受付番号など。氏名は入れない運用を推奨
    "current": None,          # 患者側に表示中のメッセージID
    "layout": None,           # 表示中の画像レイアウト（タッチ位置→ボタンの対応に使う）
    "serial_status": "未設定",
}
messages: dict[str, dict] = {}


class Hub:
    """WebSocket の接続先を役割ごとに管理する。"""

    def __init__(self) -> None:
        self.doctor: set[WebSocket] = set()
        self.patient: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def _send(self, targets: set[WebSocket], data: dict) -> None:
        for ws in list(targets):
            try:
                await ws.send_json(data)
            except Exception:  # noqa: BLE001 - 切れた接続は捨てる
                targets.discard(ws)

    async def to_doctor(self, data: dict) -> None:
        await self._send(self.doctor, data)

    async def to_patient(self, data: dict) -> None:
        await self._send(self.patient, data)

    def to_doctor_threadsafe(self, data: dict) -> None:
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.to_doctor(data), self.loop)


hub = Hub()

# ---- シリアル端末 ----
serial_dev = None


def _on_serial_status(text: str) -> None:
    state["serial_status"] = text
    hub.to_doctor_threadsafe({"type": "status", "serial": text})


def _on_touch(x: int, y: int) -> None:
    layout = state["layout"]
    if not layout:
        return
    for key, (x0, y0, x1, y1) in layout.buttons.items():
        if x0 <= x <= x1 and y0 <= y <= y1:
            _record_reply(key, "eink")
            return


def _record_reply(key: str, source: str) -> None:
    if key not in REPLY_JA:
        return
    msg = messages.get(state["current"] or "", {})
    logstore.write("patient_reply", encounter=state["encounter"], msg_id=msg.get("id"),
                   lang=msg.get("lang"), reply=key, detail=source)
    hub.to_doctor_threadsafe({"type": "reply", "key": key, "label": REPLY_JA[key], "msg_id": msg.get("id")})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global serial_dev
    hub.loop = asyncio.get_running_loop()
    threading.Thread(target=asr.preload, daemon=True).start()
    if CONFIG["serial_port"]:
        serial_dev = SerialDisplay(CONFIG["serial_port"], CONFIG["serial_baud"], _on_touch, _on_serial_status)
        state["serial_status"] = "接続待ち"
    logstore.write("server_start")
    yield


app = FastAPI(title="筆談・翻訳表示", lifespan=lifespan)


# ---- 画面 ----
@app.get("/")
def doctor_page():
    return FileResponse(STATIC / "doctor.html")


@app.get("/patient")
def patient_page():
    return FileResponse(STATIC / "patient.html")


@app.get("/api/state")
def get_state():
    return {
        "languages": {k: v[0] for k, v in LANGUAGES.items()},
        "encounter": state["encounter"],
        "asr": "準備中" if asr._model is None and not asr.error else (asr.error or "OK"),
        "translator": translator.status(),
        "serial": state["serial_status"],
        "patient_screens": len(hub.patient),
    }


class EncounterIn(BaseModel):
    label: str


@app.post("/api/encounter")
def set_encounter(body: EncounterIn):
    state["encounter"] = body.label.strip()
    logstore.write("encounter_start", encounter=state["encounter"])
    return {"encounter": state["encounter"]}


# ---- メッセージ作成 ----
def _new_message(lang: str, asr_raw: str | None) -> dict:
    if lang not in LANGUAGES:
        raise HTTPException(400, f"未対応の言語: {lang}")
    msg = {
        "id": uuid.uuid4().hex[:10],
        "lang": lang,
        "asr_raw": asr_raw,
        "source_ja": asr_raw or "",
        "translation": None,
        "back_translation": None,
        "translated_from": None,  # どの日本語から訳したか（確認後に日本語が変わっていないかの検査用）
        "sent": False,
    }
    messages[msg["id"]] = msg
    return msg


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...), lang: str = Form("ja")):
    data = await audio.read()
    suffix = Path(audio.filename or "rec.webm").suffix or ".webm"
    if CONFIG["save_audio"]:
        d = Path(CONFIG["audio_dir"])
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{datetime.now():%Y%m%d-%H%M%S}{suffix}"
        path.write_bytes(data)
        keep = True
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.write(data)
        tmp.close()
        path, keep = Path(tmp.name), False
    try:
        text = await asyncio.to_thread(asr.transcribe, path)
    except ASRUnavailable as e:
        raise HTTPException(503, str(e))
    finally:
        if not keep:
            path.unlink(missing_ok=True)
    msg = _new_message(lang, text)
    logstore.write("asr", encounter=state["encounter"], msg_id=msg["id"], lang=lang, asr_raw=text,
                   detail=str(path.name) if keep else "")
    return msg


class ManualIn(BaseModel):
    lang: str
    text: str = ""


@app.post("/api/message")
def manual_message(body: ManualIn):
    msg = _new_message(body.lang, None)
    msg["source_ja"] = body.text
    return msg


def _get(msg_id: str) -> dict:
    if msg_id not in messages:
        raise HTTPException(404, "メッセージが見つかりません")
    return messages[msg_id]


class TranslateIn(BaseModel):
    source_ja: str
    lang: str | None = None


@app.post("/api/message/{msg_id}/translate")
async def translate(msg_id: str, body: TranslateIn):
    msg = _get(msg_id)
    if body.lang:
        msg["lang"] = body.lang
    if msg["lang"] == "ja":
        raise HTTPException(400, "日本語（筆談）モードでは翻訳しません")
    src = body.source_ja.strip()
    if not src:
        raise HTTPException(400, "日本語が空です")
    try:
        tr = await asyncio.to_thread(translator.translate, src, msg["lang"])
        back = await asyncio.to_thread(translator.back_translate, tr, msg["lang"])
    except TranslationError as e:
        raise HTTPException(502, str(e))
    msg.update(source_ja=src, translation=tr, back_translation=back, translated_from=src)
    logstore.write("translate", encounter=state["encounter"], msg_id=msg_id, lang=msg["lang"],
                   source_ja=src, translation=tr, back_translation=back)
    return msg


class BackIn(BaseModel):
    translation: str


@app.post("/api/message/{msg_id}/backtranslate")
async def backtranslate(msg_id: str, body: BackIn):
    """医師（や同席の通訳者）が訳文を直接直した場合、その訳文を改めて日本語に戻して確認する。"""
    msg = _get(msg_id)
    tr = body.translation.strip()
    try:
        back = await asyncio.to_thread(translator.back_translate, tr, msg["lang"])
    except TranslationError as e:
        raise HTTPException(502, str(e))
    msg.update(translation=tr, back_translation=back)
    logstore.write("translation_edit", encounter=state["encounter"], msg_id=msg_id, lang=msg["lang"],
                   source_ja=msg["source_ja"], translation=tr, back_translation=back)
    return msg


class PreviewIn(BaseModel):
    lang: str
    text: str
    japanese: str | None = None


@app.post("/api/preview.png")
def preview(body: PreviewIn):
    """患者側の電子ペーパーに出るのと同じ画像を返す（医師の最終確認用）。"""
    layout = render.render_message(body.text, body.lang, body.japanese)
    buf = io.BytesIO()
    layout.image.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"X-Overflow": "1" if layout.overflow else "0"})


class SendIn(BaseModel):
    lang: str
    source_ja: str
    translation: str | None = None


@app.post("/api/message/{msg_id}/send")
async def send(msg_id: str, body: SendIn):
    msg = _get(msg_id)
    if body.lang not in LANGUAGES:
        raise HTTPException(400, f"未対応の言語: {body.lang}")
    if body.lang != msg["lang"]:
        # 言語を切り替えたら、前の言語での翻訳・確認は無効
        msg.update(lang=body.lang, translation=None, back_translation=None, translated_from=None)
    src = body.source_ja.strip()
    if not src:
        raise HTTPException(400, "送る内容が空です")
    if msg["lang"] == "ja":
        shown, japanese = src, None
    else:
        # 確認を経ていない訳文は送らない
        if not msg["translation"] or body.translation is None:
            raise HTTPException(409, "翻訳と確認がまだです")
        if body.translation.strip() != msg["translation"]:
            raise HTTPException(409, "訳文が確認後に変更されています。逆翻訳で確認し直してください")
        if src != msg["translated_from"]:
            raise HTTPException(409, "日本語が翻訳後に変更されています。翻訳し直してください")
        shown, japanese = msg["translation"], src

    layout = render.render_message(shown, msg["lang"], japanese)
    delivered = []
    errors = []
    if serial_dev is not None:
        frame = build_frame(TYPE_IMAGE, layout.image.width, layout.image.height, layout.to_1bpp())
        try:
            await asyncio.to_thread(serial_dev.send, frame)
            delivered.append("eink")
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    if hub.patient:
        await hub.to_patient({
            "type": "show", "text": shown, "lang": msg["lang"],
            "japanese": japanese if CONFIG["show_japanese_under_translation"] else None,
            "labels": reply_labels(msg["lang"]),
        })
        delivered.append(f"browser×{len(hub.patient)}")

    msg["source_ja"] = src
    msg["sent"] = bool(delivered)
    if delivered:
        state["current"] = msg_id
        state["layout"] = layout
    logstore.write("send", encounter=state["encounter"], msg_id=msg_id, lang=msg["lang"],
                   asr_raw=msg["asr_raw"], source_ja=src, translation=msg["translation"] if japanese else None,
                   back_translation=msg["back_translation"] if japanese else None,
                   detail=" / ".join(delivered + errors) or "表示先なし")
    if not delivered:
        raise HTTPException(503, "表示先がありません: " + (" / ".join(errors) or "患者用画面を開くか端末を接続してください"))
    return {"delivered": delivered, "errors": errors}


@app.post("/api/clear")
async def clear():
    if serial_dev is not None:
        try:
            await asyncio.to_thread(serial_dev.send, build_frame(TYPE_CLEAR, 0, 0, b""))
        except Exception:  # noqa: BLE001
            pass
    await hub.to_patient({"type": "clear"})
    state["current"] = None
    state["layout"] = None
    logstore.write("clear", encounter=state["encounter"])
    return {"ok": True}


class ReplyIn(BaseModel):
    key: str


@app.post("/api/patient/reply")
def patient_reply(body: ReplyIn):
    _record_reply(body.key, "browser")
    return {"ok": True}


@app.get("/api/logs/{day}.csv")
def export_csv(day: str):
    datetime.strptime(day, "%Y-%m-%d")  # 書式チェック（パス操作の防止も兼ねる）
    return Response(logstore.to_csv(day), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="hitsudan-{day}.csv"'})


# ---- WebSocket ----
@app.websocket("/ws/doctor")
async def ws_doctor(ws: WebSocket):
    await ws.accept()
    hub.doctor.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.doctor.discard(ws)


@app.websocket("/ws/patient")
async def ws_patient(ws: WebSocket):
    await ws.accept()
    hub.patient.add(ws)
    await hub.to_doctor({"type": "status", "patient_screens": len(hub.patient)})
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.patient.discard(ws)
        await hub.to_doctor({"type": "status", "patient_screens": len(hub.patient)})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=CONFIG["host"], port=CONFIG["port"])
