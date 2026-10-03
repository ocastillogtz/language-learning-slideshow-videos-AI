"""
languages.py
============
The target languages a workspace can teach: the 20 most widely spoken national
languages. Each entry carries what the pipeline needs to localise itself:

  name      English name — substituted for {LANGUAGE} in the script prompts
  native    the language's own name (shown in the UI)
  flag      ISO-3166 country code of the flag shown in the UI (flag-icons CSS)
  stt       ISO-639-3 code for ElevenLabs Scribe (song lyric transcription)
"""

LANGUAGES = {
    "en": {"name": "English",    "native": "English",          "flag": "gb", "stt": "eng"},
    "zh": {"name": "Mandarin Chinese", "native": "中文",        "flag": "cn", "stt": "cmn"},
    "hi": {"name": "Hindi",      "native": "हिन्दी",             "flag": "in", "stt": "hin"},
    "es": {"name": "Spanish",    "native": "Español",          "flag": "es", "stt": "spa"},
    "fr": {"name": "French",     "native": "Français",         "flag": "fr", "stt": "fra"},
    "ar": {"name": "Arabic",     "native": "العربية",          "flag": "sa", "stt": "ara"},
    "bn": {"name": "Bengali",    "native": "বাংলা",             "flag": "bd", "stt": "ben"},
    "pt": {"name": "Portuguese", "native": "Português",        "flag": "pt", "stt": "por"},
    "ru": {"name": "Russian",    "native": "Русский",          "flag": "ru", "stt": "rus"},
    "ur": {"name": "Urdu",       "native": "اردو",             "flag": "pk", "stt": "urd"},
    "id": {"name": "Indonesian", "native": "Bahasa Indonesia", "flag": "id", "stt": "ind"},
    "de": {"name": "German",     "native": "Deutsch",          "flag": "de", "stt": "deu"},
    "ja": {"name": "Japanese",   "native": "日本語",            "flag": "jp", "stt": "jpn"},
    "tr": {"name": "Turkish",    "native": "Türkçe",           "flag": "tr", "stt": "tur"},
    "ko": {"name": "Korean",     "native": "한국어",            "flag": "kr", "stt": "kor"},
    "vi": {"name": "Vietnamese", "native": "Tiếng Việt",       "flag": "vn", "stt": "vie"},
    "it": {"name": "Italian",    "native": "Italiano",         "flag": "it", "stt": "ita"},
    "pl": {"name": "Polish",     "native": "Polski",           "flag": "pl", "stt": "pol"},
    "fa": {"name": "Persian",    "native": "فارسی",            "flag": "ir", "stt": "fas"},
    "nl": {"name": "Dutch",      "native": "Nederlands",       "flag": "nl", "stt": "nld"},
}

DEFAULT_LANGUAGE = "de"


def language(code: str | None) -> dict:
    """Return the entry for `code` (with its code included); unknown → German."""
    code = code if code in LANGUAGES else DEFAULT_LANGUAGE
    return {"code": code, **LANGUAGES[code]}
