import tempfile
import time
import unittest
from pathlib import Path

from wechat_data_dirs import (
    _extract_windows_paths,
    _inspect_root,
    _resolve_account_root,
)


class WeChatDataDirTests(unittest.TestCase):
    def test_resolve_account_root_direct_and_container(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "xwechat_files"
            account = root / "wxid_demo"
            (account / "db_storage").mkdir(parents=True)
            self.assertEqual(_resolve_account_root(base), root)
            self.assertEqual(_resolve_account_root(root), root)

    def test_inspect_root_counts_accounts_and_latest_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("wxid_a", "wxid_b"):
                db_dir = root / name / "db_storage" / "message"
                db_dir.mkdir(parents=True)
                db = db_dir / "message_0.db"
                db.write_bytes(b"test")
            now = time.time()
            target = root / "wxid_b" / "db_storage" / "message" / "message_0.db"
            target.touch()
            info = _inspect_root(root, {"测试"}, root)
            self.assertEqual(info["account_count"], 2)
            self.assertTrue(info["auto_selected"])
            self.assertGreaterEqual(info["latest_mtime"], now - 5)

    def test_extract_windows_paths_from_json_and_plain_text(self):
        text = r'{"path":"D:\\WeChatData"}\nbackup=E:/Backup/xwechat_files'
        paths = _extract_windows_paths(text)
        self.assertIn(r"D:\WeChatData", paths)
        self.assertIn("E:/Backup/xwechat_files", paths)


if __name__ == "__main__":
    unittest.main()
