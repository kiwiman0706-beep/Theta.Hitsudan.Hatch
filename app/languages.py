"""対応言語と、患者側に出す返答ボタンの文言。

ボタン文言は機械翻訳を通さず、ここに確認済みの固定文言として持つ。
新しい言語を足すときは、ネイティブ話者に一度確認してもらうこと。
"""

# code: (日本語名, 英語名(翻訳プロンプト用), フォント系統)
LANGUAGES: dict[str, tuple[str, str, str]] = {
    "ja": ("日本語（翻訳なし・筆談）", "Japanese", "ja"),
    "en": ("英語", "English", "latin"),
    "zh": ("中国語（簡体字）", "Simplified Chinese", "zh"),
    "zh-TW": ("中国語（繁体字）", "Traditional Chinese", "zh"),
    "ko": ("韓国語", "Korean", "ko"),
    "vi": ("ベトナム語", "Vietnamese", "latin"),
    "tl": ("タガログ語", "Tagalog (Filipino)", "latin"),
    "pt": ("ポルトガル語（ブラジル）", "Brazilian Portuguese", "latin"),
    "es": ("スペイン語", "Spanish", "latin"),
    "id": ("インドネシア語", "Indonesian", "latin"),
    "ne": ("ネパール語", "Nepali", "deva"),
    "th": ("タイ語", "Thai", "th"),
}

# 患者が押す3つの返答: understood / again / question
REPLY_LABELS: dict[str, tuple[str, str, str]] = {
    "ja": ("わかりました", "もう一度", "質問があります"),
    "en": ("I understand", "Once more", "I have a question"),
    "zh": ("明白了", "请再说一遍", "我有问题"),
    "zh-TW": ("明白了", "請再說一遍", "我有問題"),
    "ko": ("알겠습니다", "다시 한 번", "질문이 있어요"),
    "vi": ("Tôi hiểu", "Nói lại", "Tôi có câu hỏi"),
    "tl": ("Naiintindihan ko", "Ulitin po", "May tanong ako"),
    "pt": ("Entendi", "De novo", "Tenho uma dúvida"),
    "es": ("Entiendo", "Otra vez", "Tengo una pregunta"),
    "id": ("Saya mengerti", "Sekali lagi", "Saya ada pertanyaan"),
    "ne": ("बुझें", "फेरि भन्नुहोस्", "प्रश्न छ"),
    "th": ("เข้าใจแล้ว", "อีกครั้ง", "มีคำถาม"),
}

REPLY_KEYS = ("understood", "again", "question")
REPLY_JA = {"understood": "わかりました", "again": "もう一度", "question": "質問があります"}


def font_group(code: str) -> str:
    return LANGUAGES.get(code, ("", "", "latin"))[2]


def reply_labels(code: str) -> tuple[str, str, str]:
    return REPLY_LABELS.get(code, REPLY_LABELS["en"])
