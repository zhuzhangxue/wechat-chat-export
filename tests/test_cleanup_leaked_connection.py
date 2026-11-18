import gc
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_sender_mapping import load_export_modules  # noqa: E402


def leak_connection(db_path: Path):
    """模拟上游 get_self_info()：打开连接、查询、不 close()，随后丢弃引用。"""
    conn = sqlite3.connect(db_path)
    conn.execute("SELECT 1").fetchone()
    # 函数返回后 conn 只剩下 sqlite3 语句缓存造成的循环引用


class LeakedConnectionCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core, _ = load_export_modules()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workdir = self.root / "run-test"
        self.workdir.mkdir()
        db_path = self.workdir / "contact__contact.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE contact (username TEXT)")
        conn.close()
        self.db_path = db_path

    def test_cleanup_succeeds_even_if_a_connection_was_never_closed(self):
        was_enabled = gc.isenabled()
        gc.disable()  # 让“未关闭的连接一直不被回收”稳定复现
        try:
            leak_connection(self.db_path)
            ok, error = self.core._cleanup_sensitive_workdir(self.workdir)
        finally:
            if was_enabled:
                gc.enable()
        self.assertTrue(ok, error)
        self.assertFalse(self.workdir.exists())

    def test_failed_cleanup_restores_owner_marker_for_later_auto_cleanup(self):
        marker = self.workdir / self.core.SENSITIVE_OWNER_MARKER
        marker.write_text("{}", encoding="utf-8")
        calls = []

        def failing_rmtree(path, *args, **kwargs):
            calls.append(path)
            # 模拟 rmtree 删掉了 owner 标记后，在被占用的数据库文件上失败
            if marker.exists():
                marker.unlink()
            raise PermissionError(32, "being used by another process")

        with patch.object(self.core.shutil, "rmtree", side_effect=failing_rmtree), \
                patch.object(self.core, "CLEANUP_RETRY_DELAY_SECONDS", 0):
            ok, error = self.core._cleanup_sensitive_workdir(self.workdir)

        self.assertFalse(ok)
        self.assertIn("PermissionError", error)
        self.assertEqual(len(calls), 2)  # 回收后重试了一次
        payload = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(payload["pid"], self.core.os.getpid())

    def test_retry_succeeds_after_transient_lock(self):
        calls = []
        real_rmtree = self.core.shutil.rmtree

        def flaky_rmtree(path, *args, **kwargs):
            calls.append(path)
            if len(calls) == 1:
                raise PermissionError(32, "transient lock")
            return real_rmtree(path, *args, **kwargs)

        with patch.object(self.core.shutil, "rmtree", side_effect=flaky_rmtree), \
                patch.object(self.core, "CLEANUP_RETRY_DELAY_SECONDS", 0):
            ok, error = self.core._cleanup_sensitive_workdir(self.workdir)
        self.assertTrue(ok, error)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.workdir.exists())


if __name__ == "__main__":
    unittest.main()
