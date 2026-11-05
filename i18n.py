# -*- coding: utf-8 -*-
"""Minimal UI internationalization helpers.

Default language is Chinese ("zh"). Without configuration the behavior is
identical to the pre-i18n code: ``tr(text)`` returns ``text`` unchanged.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SUPPORTED = {"zh": "中文", "ru": "Русский"}
_DEFAULT_LANG = "zh"
_CONFIG_FILE_NAME = "ui_language.json"

_language: str | None = None
_ru: dict[str, str] | None = None


def _config_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    return base / _CONFIG_FILE_NAME


def _load_config() -> str:
    path = _config_path()
    if not path.is_file():
        return _DEFAULT_LANG
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        code = data.get("language") if isinstance(data, dict) else None
    except Exception:
        return _DEFAULT_LANG
    if isinstance(code, str) and code in SUPPORTED:
        return code
    return _DEFAULT_LANG


def get_language() -> str:
    global _language
    if _language is None:
        env = os.environ.get("WECHAT_EXPORT_LANG", "")
        if env in SUPPORTED:
            _language = env
        else:
            _language = _load_config()
    return _language


def set_language_session(code: str) -> bool:
    """Set the language for the current process without writing the config file."""
    if code not in SUPPORTED:
        return False
    global _language
    _language = code
    return True


def set_language(code: str) -> bool:
    if code not in SUPPORTED:
        return False
    if not set_language_session(code):
        return False
    try:
        path = _config_path()
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump({"language": code}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _load_ru() -> dict[str, str]:
    global _ru
    if _ru is None:
        try:
            from locales.ru import RU

            _ru = dict(RU) if RU else {}
        except Exception:
            _ru = {}
    return _ru


def tr(text: str, **kwargs) -> str:
    if not isinstance(text, str):
        text = str(text)
    if get_language() == _DEFAULT_LANG:
        result = text
    else:
        result = _load_ru().get(text, text)
    if kwargs:
        result = result.format(**kwargs)
    return result
