# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import exporter_core


class StartupSensitiveCacheCleanupTests(unittest.TestCase):
    def test_dead_run_removed_active_run_and_legacy_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            with patch.object(
                exporter_core.tempfile,
                "gettempdir",
                return_value=str(temp_root),
            ):
                locations = exporter_core.sensitive_cache_locations()
                current = Path(locations["current"])
                legacy = Path(locations["legacy"])

                dead = current / "run-dead"
                active = current / "run-active"
                dead.mkdir(parents=True)
                active.mkdir(parents=True)
                legacy.mkdir(parents=True)

                (dead / exporter_core.SENSITIVE_OWNER_MARKER).write_text(
                    json.dumps({"pid": 111}),
                    encoding="utf-8",
                )
                (active / exporter_core.SENSITIVE_OWNER_MARKER).write_text(
                    json.dumps({"pid": 222}),
                    encoding="utf-8",
                )
                (legacy / "keys.json").write_text("legacy", encoding="utf-8")

                with patch.object(
                    exporter_core,
                    "_pid_is_alive",
                    side_effect=lambda pid: int(pid) == 222,
                ):
                    report = exporter_core.clear_current_sensitive_cache()

                self.assertFalse(dead.exists())
                self.assertTrue(active.exists())
                self.assertTrue(legacy.exists())
                self.assertIn(str(dead), report["removed"])
                self.assertIn(str(active), report["skipped"])
                self.assertEqual(report["failed"], [])

    def test_recent_unmarked_run_is_preserved_but_old_one_is_removed(self):
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            with patch.object(
                exporter_core.tempfile,
                "gettempdir",
                return_value=str(temp_root),
            ):
                current = Path(
                    exporter_core.sensitive_cache_locations()["current"]
                )
                recent = current / "run-recent-old-format"
                old = current / "run-stale-old-format"
                recent.mkdir(parents=True)
                old.mkdir(parents=True)

                old_time = (
                    __import__("time").time()
                    - exporter_core.UNMARKED_STALE_SECONDS
                    - 60
                )
                os.utime(old, (old_time, old_time))

                report = exporter_core.clear_current_sensitive_cache()

                self.assertTrue(recent.exists())
                self.assertFalse(old.exists())
                self.assertIn(str(recent), report["skipped"])
                self.assertIn(str(old), report["removed"])

    def test_bom_encoded_owner_marker_is_supported(self):
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            with patch.object(
                exporter_core.tempfile,
                "gettempdir",
                return_value=str(temp_root),
            ):
                current = Path(
                    exporter_core.sensitive_cache_locations()["current"]
                )
                dead = current / "run-bom-dead"
                dead.mkdir(parents=True)

                (dead / exporter_core.SENSITIVE_OWNER_MARKER).write_text(
                    json.dumps({"pid": 2147483647}),
                    encoding="utf-8-sig",
                )

                with patch.object(
                    exporter_core,
                    "_pid_is_alive",
                    return_value=False,
                ):
                    report = exporter_core.clear_current_sensitive_cache()

                self.assertFalse(dead.exists())
                self.assertIn(str(dead), report["removed"])
                self.assertEqual(report["failed"], [])

    def test_new_workdir_writes_owner_marker(self):
        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)
            with patch.object(
                exporter_core.tempfile,
                "gettempdir",
                return_value=str(temp_root),
            ):
                workdir = exporter_core._create_sensitive_workdir()
                marker = workdir / exporter_core.SENSITIVE_OWNER_MARKER
                self.assertTrue(marker.is_file())
                payload = json.loads(marker.read_text(encoding="utf-8"))
                self.assertEqual(payload["pid"], os.getpid())

                exporter_core._cleanup_sensitive_workdir(workdir)

                self.assertFalse(workdir.exists())


if __name__ == "__main__":
    unittest.main()
