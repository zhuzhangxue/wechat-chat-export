# -*- coding: utf-8 -*-
"""Tests for the minimal i18n layer."""
from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import i18n
from i18n import get_language, set_language_session, tr


class TestI18N(unittest.TestCase):
    def _collect_tr_args(self) -> set[str]:
        """Collect all first positional arguments to tr() calls in *.py files."""
        project_root = Path(__file__).resolve().parent.parent
        args: set[str] = set()
        for path in project_root.rglob("*.py"):
            if path.name == "ru.py" and path.parent.name == "locales":
                # The translation dictionary itself is not a call site.
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Name) and func.id == "tr":
                    if node.args:
                        first = node.args[0]
                        if isinstance(first, ast.Constant) and isinstance(first.value, str):
                            args.add(first.value)
        return args

    def _ru_dict(self) -> dict[str, str]:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "locales.ru",
            Path(__file__).resolve().parent.parent / "locales" / "ru.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return dict(module.RU)

    def test_zh_returns_original_for_all_ru_keys(self):
        """With zh, tr() must return the original Chinese string unchanged."""
        ru = self._ru_dict()
        set_language_session("zh")
        for key in ru:
            with self.subTest(key=key):
                self.assertEqual(tr(key), key)

    def test_all_ru_keys_are_used_in_code(self):
        """Every key in RU must appear as a literal argument to tr()."""
        ru = self._ru_dict()
        args = self._collect_tr_args()
        for key in ru:
            with self.subTest(key=key):
                self.assertIn(
                    key,
                    args,
                    f"RU key not used as tr() argument: {key!r}",
                )

    def test_placeholder_sets_match(self):
        """Placeholder names in Russian translation must match the Chinese template."""
        import string

        ru = self._ru_dict()
        for key, value in ru.items():
            with self.subTest(key=key):
                key_placeholders = {
                    name for _, name, _, _ in string.Formatter().parse(key) if name
                }
                val_placeholders = {
                    name for _, name, _, _ in string.Formatter().parse(value) if name
                }
                self.assertEqual(
                    key_placeholders,
                    val_placeholders,
                    f"Placeholder mismatch for {key!r}",
                )

    def test_env_var_selects_russian(self):
        """WECHAT_EXPORT_LANG=ru must produce Russian output."""
        ru = self._ru_dict()
        with mock.patch.dict(os.environ, {"WECHAT_EXPORT_LANG": "ru"}):
            # Force re-read from environment.
            i18n._language = None
            self.assertEqual(get_language(), "ru")
            for key, expected in ru.items():
                with self.subTest(key=key):
                    self.assertEqual(tr(key), expected)

    def test_unknown_language_defaults_to_chinese(self):
        """Unknown WECHAT_EXPORT_LANG values fall back to zh."""
        with mock.patch.dict(os.environ, {"WECHAT_EXPORT_LANG": "xx"}):
            i18n._language = None
            self.assertEqual(get_language(), "zh")
            self.assertEqual(tr("开始导出"), "开始导出")


if __name__ == "__main__":
    unittest.main()
