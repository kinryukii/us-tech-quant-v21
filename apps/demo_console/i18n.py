"""Local display translations, isolated per render context; economic values stay raw."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import json
from pathlib import Path

LANGUAGES = {"zh": "中文", "ja": "日本語", "en": "English"}
_language = ContextVar("demo_display_language", default="en")


def get_language() -> str:
    return _language.get()


def set_language(code: str):
    return _language.set(code if code in LANGUAGES else "en")


@contextmanager
def language_scope(code: str):
    token = set_language(code)
    try:
        yield
    finally:
        _language.reset(token)


@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads(Path(__file__).with_name("translations.json").read_text(encoding="utf-8"))


def tr(source: str, **values) -> str:
    """Translate a fixed UI message, then interpolate supplied display values."""
    translated = source if get_language() == "en" else catalog().get(source, {}).get(get_language(), source)
    return translated.format(**values) if values else translated


def option_labeler(options):
    """Freeze this render's labels for deferred widget serialization."""
    labels = {option: tr(option) for option in options}
    return labels.__getitem__
