import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_core():
    wechatauto = ModuleType("wechatauto")
    wechatauto.WeChatDB = Mock(side_effect=AssertionError("Real WeChatDB is forbidden"))
    wechatauto.MediaDownloader = Mock(side_effect=AssertionError("Media is forbidden"))

    zstandard = ModuleType("zstandard")
    zstandard.ZstdDecompressor = Mock(side_effect=AssertionError("No compressed fixtures"))

    pillow = ModuleType("PIL")
    pillow.Image = Mock()
    pillow.ImageStat = Mock()

    with patch.dict(sys.modules, {
        "wechatauto": wechatauto,
        "zstandard": zstandard,
        "PIL": pillow,
    }):
        spec = importlib.util.spec_from_file_location(
            "_sensitive_cache_exporter_core",
            ROOT / "exporter_core.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class SensitiveCacheTests(unittest.TestCase):
    def setUp(self):
        self.core = load_core()

    def test_export_uses_one_time_workdir_and_removes_it_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            seen = {}
            logs = []

            def fake_impl(keyword, **kwargs):
                workdir = Path(kwargs["workdir"])
                seen["workdir"] = workdir
                self.assertTrue(workdir.is_dir())
                self.assertTrue(
                    (workdir / self.core.SENSITIVE_OWNER_MARKER).is_file()
                )
                (workdir / "keys.json").write_text('{"secret":"value"}', encoding="utf-8")
                (workdir / "decrypted.db").write_bytes(b"SQLite format 3")
                return {"chat_name": keyword}

            with (
                patch.object(self.core.tempfile, "gettempdir", return_value=str(temp_root)),
                patch.object(self.core, "_export_chat_impl", side_effect=fake_impl),
            ):
                result = self.core.export_chat("Synthetic", progress=logs.append)

            self.assertFalse(seen["workdir"].exists())
            self.assertTrue(result["sensitive_cache_cleanup"])
            self.assertIsNone(result["sensitive_cache_cleanup_error"])
            self.assertTrue(any("敏感临时缓存已清理" in line for line in logs))

    def test_export_removes_workdir_when_export_raises(self):
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            seen = {}

            def fake_impl(keyword, **kwargs):
                workdir = Path(kwargs["workdir"])
                seen["workdir"] = workdir
                (workdir / "keys.json").write_text("secret", encoding="utf-8")
                raise RuntimeError("synthetic failure")

            with (
                patch.object(self.core.tempfile, "gettempdir", return_value=str(temp_root)),
                patch.object(self.core, "_export_chat_impl", side_effect=fake_impl),
            ):
                with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                    self.core.export_chat("Synthetic")

            self.assertFalse(seen["workdir"].exists())


    def test_startup_cleanup_removes_dead_run_but_preserves_active_and_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            with patch.object(
                self.core.tempfile,
                "gettempdir",
                return_value=str(temp_root),
            ):
                locations = self.core.sensitive_cache_locations()
                current = Path(locations["current"])
                legacy = Path(locations["legacy"])
                dead = current / "run-dead"
                active = current / "run-active"
                dead.mkdir(parents=True)
                active.mkdir(parents=True)
                legacy.mkdir(parents=True)

                (dead / self.core.SENSITIVE_OWNER_MARKER).write_text(
                    '{"pid": 111}',
                    encoding="utf-8",
                )
                (active / self.core.SENSITIVE_OWNER_MARKER).write_text(
                    '{"pid": 222}',
                    encoding="utf-8",
                )
                (dead / "keys.json").write_text("dead secret", encoding="utf-8")
                (active / "keys.json").write_text("active secret", encoding="utf-8")
                (legacy / "keys.json").write_text("legacy secret", encoding="utf-8")

                with patch.object(
                    self.core,
                    "_pid_is_alive",
                    side_effect=lambda pid: int(pid) == 222,
                ):
                    report = self.core.clear_current_sensitive_cache()

            self.assertFalse(dead.exists())
            self.assertTrue(active.exists())
            self.assertTrue(legacy.exists())
            self.assertIn(str(dead), report["removed"])
            self.assertIn(str(active), report["skipped"])
            self.assertEqual(report["failed"], [])

    def test_startup_cleanup_preserves_recent_unmarked_run(self):
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            with patch.object(
                self.core.tempfile,
                "gettempdir",
                return_value=str(temp_root),
            ):
                current = Path(
                    self.core.sensitive_cache_locations()["current"]
                )
                recent = current / "run-old-format"
                recent.mkdir(parents=True)
                (recent / "keys.json").write_text("secret", encoding="utf-8")

                report = self.core.clear_current_sensitive_cache()

            self.assertTrue(recent.exists())
            self.assertIn(str(recent), report["skipped"])
            self.assertEqual(report["removed"], [])
            self.assertEqual(report["failed"], [])

    def test_manual_cleanup_only_removes_known_sensitive_roots(self):
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            with patch.object(
                self.core.tempfile,
                "gettempdir",
                return_value=str(temp_root),
            ):
                locations = self.core.sensitive_cache_locations()
                current = Path(locations["current"])
                legacy = Path(locations["legacy"])
                unrelated = temp_root / "unrelated"

                current.mkdir(parents=True)
                legacy.mkdir(parents=True)
                unrelated.mkdir()
                (current / "keys.json").write_text("secret", encoding="utf-8")
                (legacy / "image_keys.json").write_text("secret", encoding="utf-8")
                (unrelated / "keep.txt").write_text("keep", encoding="utf-8")

                report = self.core.clear_sensitive_cache()

            self.assertFalse(current.exists())
            self.assertFalse(legacy.exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(report["failed"], [])
            self.assertEqual(set(report["removed"]), {str(current), str(legacy)})

    def test_cleanup_failure_is_reported_without_hiding_export_result(self):
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            seen = {}

            def fake_impl(keyword, **kwargs):
                workdir = Path(kwargs["workdir"])
                seen["workdir"] = workdir
                (workdir / "keys.json").write_text("secret", encoding="utf-8")
                return {"chat_name": keyword}

            real_rmtree = self.core.shutil.rmtree

            def fail_target(path, *args, **kwargs):
                if Path(path) == seen.get("workdir"):
                    raise OSError("locked")
                return real_rmtree(path, *args, **kwargs)

            with (
                patch.object(self.core.tempfile, "gettempdir", return_value=str(temp_root)),
                patch.object(self.core, "_export_chat_impl", side_effect=fake_impl),
                patch.object(self.core.shutil, "rmtree", side_effect=fail_target),
            ):
                result = self.core.export_chat("Synthetic")

            self.assertFalse(result["sensitive_cache_cleanup"])
            self.assertIn("locked", result["sensitive_cache_cleanup_error"])
            self.assertTrue(seen["workdir"].exists())


if __name__ == "__main__":
    unittest.main()
