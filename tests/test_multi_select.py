import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import chat_picker  # noqa: E402
from test_sender_mapping import load_export_modules  # noqa: E402


CHATS = [
    {"username": "111@chatroom", "name": "项目群", "is_group": True, "last_time": 300},
    {"username": "wxid_a", "name": "Alice", "is_group": False, "last_time": 200},
    {"username": "wxid_b", "name": "Bob", "is_group": False, "last_time": 100},
    {"username": "222@chatroom", "name": "家人群", "is_group": True, "last_time": None},
]


class KeywordDB:
    """Minimal DB for find_contact(): maps keyword → contact record."""

    def __init__(self, contacts):
        self.contacts = contacts

    def search_contact(self, keyword):
        return [c for c in self.contacts if keyword in (c.get("remark") or "")
                or keyword in (c.get("nick_name") or "")]

    def _message_dbs(self):
        return []


class SelectChatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core, _ = load_export_modules()

    def test_usernames_keep_order_dedupe_and_report_missing(self):
        logs = []
        picked, missing = self.core._select_chats(
            None, CHATS, ["wxid_b", "111@chatroom", "wxid_b", "wxid_ghost"], [], logs.append,
        )
        self.assertEqual([c["username"] for c in picked], ["wxid_b", "111@chatroom"])
        self.assertEqual([m["query"] for m in missing], ["wxid_ghost"])
        self.assertTrue(any("wxid_ghost" in line for line in logs))

    def test_keywords_resolve_through_contact_search(self):
        db = KeywordDB([
            {"username": "wxid_a", "remark": "Alice", "nick_name": "a"},
            {"username": "wxid_only_contact", "remark": "从没聊过", "nick_name": ""},
        ])
        picked, missing = self.core._select_chats(
            db, CHATS, ["wxid_a"], ["Alice", "从没聊过", "不存在的人"], lambda _m: None,
        )
        # Alice 同时被 username 和名字选中，只导出一次
        self.assertEqual([c["username"] for c in picked], ["wxid_a"])
        self.assertEqual([m["query"] for m in missing], ["从没聊过", "不存在的人"])
        self.assertIn("没有找到", missing[1]["reason"])


class ExportSelectedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core, _ = load_export_modules()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def _run(self, **kwargs):
        exported = []

        def fake_impl(**impl_kwargs):
            contact = impl_kwargs["contact"]
            exported.append(contact["username"])
            folder = impl_kwargs["folder_name"]
            out = Path(impl_kwargs["out_root"]) / folder
            out.mkdir(parents=True, exist_ok=True)
            return {
                "message_count": 2, "output_dir": str(out),
                "txt": str(out / "a.txt"), "md": str(out / "a.md"), "json": str(out / "a.json"),
                "media_stats": {}, "sender_resolution_counts": {},
            }

        with patch.object(self.core, "WeChatDB", return_value=object()), \
                patch.object(self.core, "_batch_chat_candidates", return_value=([dict(c) for c in CHATS], 0)), \
                patch.object(self.core, "_export_chat_impl", side_effect=fake_impl):
            result = self.core.export_all_chats(self.root / "out", **kwargs)
        return result, exported

    def test_only_selected_chats_are_exported_with_selected_index(self):
        result, exported = self._run(usernames=["wxid_b", "222@chatroom", "wxid_ghost"])
        self.assertEqual(exported, ["wxid_b", "222@chatroom"])
        self.assertEqual(result["selection"], "selected")
        self.assertEqual(result["selected_total"], 2)
        self.assertEqual(result["discovered_total"], 4)
        self.assertEqual([m["query"] for m in result["not_found"]], ["wxid_ghost"])
        self.assertTrue(result["index_md"].endswith("selected_chats_index.md"))
        md = Path(result["index_md"]).read_text(encoding="utf-8")
        self.assertIn("# 选中聊天导出索引", md)
        self.assertIn("wxid_ghost", md)
        self.assertNotIn("Alice", md)
        data = json.loads(Path(result["index_json"]).read_text(encoding="utf-8-sig"))
        self.assertEqual([c["username"] for c in data["chats"]], ["wxid_b", "222@chatroom"])
        self.assertFalse((self.root / "out" / "all_chats_index.md").exists())

    def test_export_all_is_unchanged(self):
        result, exported = self._run()
        self.assertEqual(len(exported), 4)
        self.assertEqual(result["selection"], "all")
        self.assertEqual(result["not_found"], [])
        self.assertTrue(result["index_md"].endswith("all_chats_index.md"))

    def test_empty_selection_is_rejected_before_touching_database(self):
        with patch.object(self.core, "WeChatDB") as constructor:
            with self.assertRaises(ValueError):
                self.core.export_all_chats(self.root, usernames=[])
            with self.assertRaises(ValueError):
                self.core.export_selected_chats(usernames=["  "], out_root=self.root)
        constructor.assert_not_called()

    def test_selection_where_nothing_matches_is_an_error(self):
        with self.assertRaises(ValueError) as ctx:
            self._run(usernames=["wxid_ghost"])
        self.assertIn("wxid_ghost", str(ctx.exception))

    def test_list_chats_uses_sandbox_and_cleans_up(self):
        seen_workdirs = []

        def fake_db(db_dir=None, workdir=None):
            seen_workdirs.append(Path(workdir))
            self.assertTrue(Path(workdir).exists())
            return object()

        with patch.object(self.core, "WeChatDB", side_effect=fake_db), \
                patch.object(self.core, "_batch_chat_candidates", return_value=([dict(c) for c in CHATS], 1)):
            listing = self.core.list_chats()
        self.assertEqual([c["username"] for c in listing["chats"]], [c["username"] for c in CHATS])
        self.assertEqual(listing["unresolved_message_tables"], 1)
        self.assertEqual(listing["chats"][3]["last_time_text"], "")
        self.assertFalse(seen_workdirs[0].exists())
        self.assertTrue(listing["sensitive_cache_cleanup"])
        self.assertIsNone(listing["sensitive_cache_cleanup_error"])

    def test_list_chats_cleans_up_when_reading_fails(self):
        seen_workdirs = []

        def broken_db(db_dir=None, workdir=None):
            seen_workdirs.append(Path(workdir))
            raise RuntimeError("decrypt failed")

        with patch.object(self.core, "WeChatDB", side_effect=broken_db):
            with self.assertRaises(RuntimeError):
                self.core.list_chats()
        self.assertFalse(seen_workdirs[0].exists())


class FilterChatsTests(unittest.TestCase):
    def test_query_and_kind(self):
        f = chat_picker.filter_chats
        self.assertEqual(len(f(CHATS)), 4)
        self.assertEqual([c["username"] for c in f(CHATS, kind="群聊")], ["111@chatroom", "222@chatroom"])
        self.assertEqual([c["username"] for c in f(CHATS, kind="私聊")], ["wxid_a", "wxid_b"])
        self.assertEqual([c["username"] for c in f(CHATS, "alice")], ["wxid_a"])
        self.assertEqual([c["username"] for c in f(CHATS, "群")], ["111@chatroom", "222@chatroom"])
        self.assertEqual([c["username"] for c in f(CHATS, "wxid_b")], ["wxid_b"])
        self.assertEqual(f(CHATS, "群", kind="私聊"), [])


class ChatPickerWidgetTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover - headless CI without display
            self.skipTest(f"Tk unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_selection_survives_filtering_and_confirm_returns_original_order(self):
        confirmed = []
        picker = chat_picker.ChatPicker(self.root, CHATS, on_confirm=confirmed.append)
        self.assertEqual(str(picker.confirm_btn["state"]), "disabled")

        picker.toggle(["wxid_b"])
        picker.query_var.set("群")  # 过滤后 wxid_b 不可见，但仍保持勾选
        picker._check_visible()
        self.assertEqual(picker.selected, {"wxid_b", "111@chatroom", "222@chatroom"})
        self.assertIn("1 个已选不在当前筛选中", picker.count_var.get())

        picker.toggle(["111@chatroom", "222@chatroom"])  # 全部已勾 → 统一取消
        self.assertEqual(picker.selected, {"wxid_b"})
        picker.toggle(["111@chatroom", "wxid_b"])  # 混合状态 → 统一勾上
        self.assertEqual(picker.selected, {"wxid_b", "111@chatroom"})

        picker._confirm()
        self.assertEqual(confirmed, [["111@chatroom", "wxid_b"]])

    def test_preselected_unknown_usernames_are_dropped(self):
        picker = chat_picker.ChatPicker(
            self.root, CHATS, on_confirm=lambda _u: None, selected={"wxid_a", "gone"},
        )
        self.assertEqual(picker.selected, {"wxid_a"})
        picker.destroy()


if __name__ == "__main__":
    unittest.main()
