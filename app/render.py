"""患者側の電子ペーパー用に、文字をPC側で画像化する。

端末側にフォントを持たせず、PCで描いた白黒画像を送るだけにしている。
こうすると端末は「画像を受けて出すだけ」になり、タイ語・ネパール語など
フォントや字形処理が難しい言語も、PC側のフォントを差し替えるだけで対応できる。
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import CONFIG
from languages import font_group, reply_labels, REPLY_KEYS

NO_SPACE_GROUPS = {"ja", "zh", "th"}
# 行頭に来てはいけない文字（簡易な禁則処理）
NO_LINE_START = set("、。，．,.)）」』】〕〉》！？!?ー…・：；:;ぁぃぅぇぉっゃゅょァィゥェォッャュョ")

MARGIN = 28
BUTTON_H = 96


class Layout:
    def __init__(self, image: Image.Image, buttons: dict[str, tuple[int, int, int, int]], overflow: bool = False):
        self.image = image
        self.buttons = buttons  # key -> (x0, y0, x1, y1)
        self.overflow = overflow  # 最小の文字サイズでも収まらなかった

    def to_1bpp(self) -> bytes:
        """1ピクセル1ビット、行ごとにMSBから詰める。1=黒。"""
        bw = self.image.convert("L").point(lambda v: 255 if v < 128 else 0).convert("1", dither=Image.Dither.NONE)
        return bw.tobytes()


@lru_cache(maxsize=64)
def _font(group: str, size: int) -> ImageFont.FreeTypeFont:
    for path in CONFIG["fonts"].get(group, []) + CONFIG["fonts"]["ja"]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise FileNotFoundError(
        f"フォントが見つかりません（{group}）。fonts/ に Noto Sans を置くか config.local.json の fonts を設定してください"
    )


def _tokens(text: str, group: str) -> list[str]:
    """改行可能な単位に分割する。"""
    if group not in NO_SPACE_GROUPS:
        out: list[str] = []
        for i, word in enumerate(text.split(" ")):
            out.append((" " if i else "") + word)
        return out
    out = []
    for ch in text:
        # 結合文字（タイ語の母音記号など）と行頭禁則文字は直前にくっつける
        if out and (unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Mc") or ch in NO_LINE_START):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int, group: str) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for tok in _tokens(para, group):
            cand = line + tok
            if line and font.getlength(cand) > width:
                lines.append(line)
                line = tok.lstrip(" ")
            else:
                line = cand
        lines.append(line)
    return lines


def _fit(text: str, group: str, width: int, height: int, max_px: int, min_px: int):
    """枠に収まる最大の文字サイズを探す。"""
    size = max_px
    while True:
        font = _font(group, size)
        lines = _wrap(text, font, width, group)
        line_h = int(size * 1.3)
        if len(lines) * line_h <= height or size <= min_px:
            return font, lines, line_h
        size -= 4


def render_message(text: str, lang: str, japanese: str | None = None) -> Layout:
    W, H = CONFIG["display_width"], CONFIG["display_height"]
    img = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(img)
    group = font_group(lang)

    body_bottom = H - BUTTON_H - MARGIN
    sub_h = 0
    if japanese and lang != "ja" and CONFIG["show_japanese_under_translation"]:
        sub_font, sub_lines, sub_lh = _fit(japanese, "ja", W - 2 * MARGIN, 90, 30, 20)
        sub_h = len(sub_lines) * sub_lh + 16
        y = body_bottom - sub_h + 16
        draw.line((MARGIN, y - 10, W - MARGIN, y - 10), fill=160, width=2)
        for ln in sub_lines:
            draw.text((MARGIN, y), ln, font=sub_font, fill=80)
            y += sub_lh

    font, lines, line_h = _fit(
        text, group, W - 2 * MARGIN, body_bottom - MARGIN - sub_h, CONFIG["font_max_px"], CONFIG["font_min_px"]
    )
    area_bottom = body_bottom - sub_h
    overflow = MARGIN + len(lines) * line_h > area_bottom
    y = MARGIN
    for ln in lines:
        if y + line_h > area_bottom:
            break  # はみ出す行は描かない（医師側の画面で警告する）
        draw.text((MARGIN, y), ln, font=font, fill=0)
        y += line_h

    buttons = _draw_buttons(draw, lang, W, H)
    return Layout(img, buttons, overflow)


def _draw_buttons(draw: ImageDraw.ImageDraw, lang: str, W: int, H: int):
    labels = reply_labels(lang)
    group = font_group(lang)
    gap = 16
    bw = (W - 2 * MARGIN - 2 * gap) // 3
    y0, y1 = H - BUTTON_H - 12, H - 12
    buttons = {}
    for i, (key, label) in enumerate(zip(REPLY_KEYS, labels)):
        x0 = MARGIN + i * (bw + gap)
        x1 = x0 + bw
        draw.rounded_rectangle((x0, y0, x1, y1), radius=14, outline=0, width=4)
        font, lines, lh = _fit(label, group, bw - 20, BUTTON_H - 16, 34, 18)
        ty = y0 + (BUTTON_H - len(lines) * lh) // 2
        for ln in lines:
            tw = font.getlength(ln)
            draw.text((x0 + (bw - tw) / 2, ty), ln, font=font, fill=0)
            ty += lh
        buttons[key] = (x0, y0, x1, y1)
    return buttons


def render_blank() -> Layout:
    W, H = CONFIG["display_width"], CONFIG["display_height"]
    return Layout(Image.new("L", (W, H), 255), {})
