"""翻訳と逆翻訳（確認用に日本語へ戻す）。

逆翻訳は「順翻訳とは別の会話」で行う。同じ会話の中だと元の日本語を覚えていて、
訳文に誤りがあっても元の意味で日本語に戻してしまい、確認にならないため。

翻訳エンジンは設定 translator で切り替える: "gemini"（既定）/ "claude" / "none"
"""
from __future__ import annotations

from config import CONFIG
from languages import LANGUAGES

FORWARD_SYSTEM = """あなたは病院の診察室で働く医療通訳です。医師が患者に伝える日本語を、指定された言語に翻訳してください。

- 意味を正確に。情報を足したり省いたり、言い換えて和らげたりしない。
- 数値・単位・薬の名前・回数・日付・左右は一字一句そのまま正確に移す。
- 患者が読む文なので、専門用語は一般の人が理解できる平易な語にする。ただし意味は変えない。
- 原文が曖昧・誤認識らしい箇所があっても推測で補わず、そのまま訳す（医師が確認画面で気づけるように）。
- 出力は訳文のみ。前置き・注釈・引用符・原文は付けない。"""

BACK_SYSTEM = """あなたは翻訳の検証担当です。与えられた文を、日本語に「直訳」してください。

- 目的は訳文の誤りを医師が見つけること。自然な日本語に整えたり、意図を推測して補正したりしない。
- 不自然な点・意味が通らない点は、不自然なまま日本語にする。
- 数値・単位・薬の名前・左右は正確に。
- 出力は日本語訳のみ。前置きや注釈は付けない。"""


class TranslationError(RuntimeError):
    pass


class _Gemini:
    """Google Gemini API。APIキーは環境変数 GEMINI_API_KEY から読む。"""

    def __init__(self) -> None:
        from google import genai
        from google.genai import errors, types

        self._types = types
        self._errors = errors
        self._client = genai.Client()

    def call(self, system: str, text: str) -> str:
        types, errors = self._types, self._errors
        try:
            response = self._client.models.generate_content(
                model=CONFIG["gemini_model"],
                contents=text,
                config=types.GenerateContentConfig(system_instruction=system),
            )
        except errors.ClientError as e:
            if e.code == 429:
                raise TranslationError("翻訳APIの利用上限に達しました。少し待って再試行してください") from e
            if e.code in (401, 403) or "API key" in (e.message or ""):
                raise TranslationError("Gemini APIキーが無効です（環境変数 GEMINI_API_KEY を確認）") from e
            raise TranslationError(f"翻訳APIエラー ({e.code}): {e.message}") from e
        except errors.APIError as e:
            raise TranslationError(f"翻訳APIエラー ({e.code}): {e.message}") from e
        except OSError as e:
            raise TranslationError(f"翻訳サーバーに接続できません: {e}") from e

        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and feedback.block_reason:
            raise TranslationError(f"翻訳が拒否されました（{feedback.block_reason}）。表現を変えて再試行してください")
        out = (response.text or "").strip()
        if not out:
            raise TranslationError("翻訳結果が空でした。もう一度試してください")
        return out


class _Claude:
    """Anthropic Claude API。APIキーは環境変数 ANTHROPIC_API_KEY から読む。"""

    def __init__(self) -> None:
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic()

    def call(self, system: str, text: str) -> str:
        anthropic = self._anthropic
        try:
            response = self._client.beta.messages.create(
                model=CONFIG["claude_model"],
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": text}],
                output_config={"effort": CONFIG["claude_effort"]},
                # 安全分類器による誤拒否時は、サーバー側で別モデルに自動で切り替える
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIConnectionError as e:
            raise TranslationError(f"翻訳サーバーに接続できません: {e}") from e
        except anthropic.RateLimitError as e:
            raise TranslationError("翻訳APIの利用上限に達しました。少し待って再試行してください") from e
        except anthropic.APIStatusError as e:
            raise TranslationError(f"翻訳APIエラー ({e.status_code}): {e.message}") from e

        if response.stop_reason == "refusal":
            raise TranslationError("翻訳が拒否されました。表現を変えて再試行してください")
        out = "".join(b.text for b in response.content if b.type == "text").strip()
        if not out:
            raise TranslationError("翻訳結果が空でした")
        return out


_BACKENDS = {"gemini": _Gemini, "claude": _Claude}


class Translator:
    def __init__(self) -> None:
        self.name = CONFIG["translator"]
        self.error: str | None = None
        self._backend = None
        if self.name in _BACKENDS:
            try:
                self._backend = _BACKENDS[self.name]()
            except Exception as e:  # noqa: BLE001 - 起動は止めず、画面に理由を出す（筆談は使える）
                self.error = f"{self.name}: {e}"

    @property
    def enabled(self) -> bool:
        return self._backend is not None

    def status(self) -> str:
        if self._backend:
            return f"OK（{self.name}）"
        return self.error or "無効"

    def _call(self, system: str, text: str) -> str:
        if not self._backend:
            raise TranslationError("翻訳が使えません: " + (self.error or "設定 translator=none"))
        return self._backend.call(system, text)

    def translate(self, japanese: str, lang: str) -> str:
        target = LANGUAGES[lang][1]
        return self._call(FORWARD_SYSTEM, f"翻訳先の言語: {target}\n\n---\n{japanese}")

    def back_translate(self, text: str, lang: str) -> str:
        source = LANGUAGES[lang][1]
        return self._call(BACK_SYSTEM, f"原文の言語: {source}\n\n---\n{text}")
