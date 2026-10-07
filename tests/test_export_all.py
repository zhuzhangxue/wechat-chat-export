# -*- coding: utf-8 -*-
import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_core():
    # 注入桩模块：加载完整生产模块，但禁止真实 WeChatDB 与媒体访问。
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
            "_export_all_exporter_core",
            ROOT / "exporter_core.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def make_contact_db(path, rows):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "CREATE TABLE Contact (username TEXT, remark TEXT, nick_name TEXT)"
        )
        conn.executemany(
            "INSERT INTO Contact (username, remark, nick_name) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()


def make_message_shard(path, name2id, message_usernames):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
        conn.executemany(
            "INSERT INTO Name2Id (rowid, user_name) VALUES (?, ?)",
            list(name2id.items()),
        )
        for username in message_usernames:
            table = "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()
            conn.execute(f'CREATE TABLE "{table}" (local_id INTEGER)')
        conn.commit()


def make_full_shard(path, name2id, user_messages):
    """建立可用于真实读取的消息分片：{username: [消息行覆盖, ...]}。"""
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
        conn.executemany(
            "INSERT INTO Name2Id (rowid, user_name) VALUES (?, ?)",
            list(name2id.items()),
        )
        for username, messages in user_messages.items():
            table = "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()
            conn.execute(
                f'CREATE TABLE "{table}" ('
                "local_id INTEGER, local_type INTEGER, server_id INTEGER, "
                "real_sender_id, create_time INTEGER, message_content TEXT, "
                "compress_content TEXT, sort_seq INTEGER)"
            )
            for index, message in enumerate(messages, 1):
                row = {
                    "local_id": index,
                    "local_type": 1,
                    "server_id": 1000 + index,
                    "real_sender_id": 2,
                    "create_time": 1700000000 + index,
                    "message_content": f"消息{index}",
                    "compress_content": None,
                    "sort_seq": index,
                }
                row.update(message)
                conn.execute(
                    f'INSERT INTO "{table}" ({", ".join(row)}) '
                    f'VALUES ({", ".join("?" for _ in row)})',
                    tuple(row.values()),
                )
        conn.commit()


class FakeDB:
    """只实现 exporter_core 实际用到的接口。"""

    def __init__(self, root, nicks=None, self_username="wxid_self"):
        self.root = Path(root)
        self.nicks = dict(nicks or {})
        self.self_info = {"username": self_username, "nick_name": "Self"}
        self._db_files = []
        self.paths = {}
        self.shard_rels = []
        self.sessions = []
        self.message_chats = []

    def add_db(self, name, path, shard=False):
        rel = name.replace("/", "\\")
        self._db_files.append((rel, str(path)))
        self.paths[rel] = Path(path)
        if shard:
            self.shard_rels.append(rel)
        return rel

    def _nickname_index(self):
        return dict(self.nicks)

    def get_self_info(self):
        return dict(self.self_info)

    def get_sessions(self, limit=100):
        return [dict(item) for item in self.sessions[:limit]]

    def list_message_chats(self):
        return [dict(item) for item in self.message_chats]

    def _message_dbs(self):
        return list(self.shard_rels)

    def _open(self, rel):
        return sqlite3.connect(Path(self.paths[rel]).as_uri() + "?mode=ro", uri=True)


class ListContactsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = load_core()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_filters_special_accounts_and_respects_flags(self):
        db = FakeDB(self.root, nicks={
            "wxid_friend": "好友",
            "111@chatroom": "群聊",
            "filehelper": "文件传输助手",
            "gh_abc123": "某公众号",
            "weixin": "微信团队",
            "wxid_no_name": "",
        })
        logs = []
        rows = self.core.list_contacts(db, progress=logs.append)

        self.assertEqual(
            {item["username"] for item in rows},
            {"wxid_friend", "wxid_no_name", "111@chatroom"},
        )
        # 私聊在前、群聊在后。
        self.assertEqual([item["is_group"] for item in rows], [False, False, True])
        names = {item["username"]: item["name"] for item in rows}
        self.assertEqual(names["wxid_friend"], "好友")
        # 没有显示名时回落为 username，而不是留空。
        self.assertEqual(names["wxid_no_name"], "wxid_no_name")
        self.assertTrue(any("已跳过 3 个" in line for line in logs))

        only_groups = self.core.list_contacts(db, include_private=False)
        self.assertEqual([item["username"] for item in only_groups], ["111@chatroom"])

        only_private = self.core.list_contacts(db, include_group=False)
        self.assertEqual(
            {item["username"] for item in only_private},
            {"wxid_friend", "wxid_no_name"},
        )

    def test_merges_contact_db_and_message_shards(self):
        contact_db = self.root / "contact.db"
        make_contact_db(contact_db, [
            ("wxid_c", "C备注", "C昵称"),
            ("222@chatroom", "", "群B"),
            ("gh_official", "", "公众号"),
            ("filehelper", "", "文件传输助手"),
        ])
        shard = self.root / "message_0.db"
        make_message_shard(
            shard,
            {2: "wxid_d", 9: "wxid_group_member"},
            ["wxid_d"],
        )
        db = FakeDB(self.root, nicks={"wxid_d": "D昵称"})
        db.add_db("contact/contact.db", contact_db)
        db.add_db("message/message_0.db", shard, shard=True)

        rows = self.core.list_contacts(db)
        names = {item["username"]: item["name"] for item in rows}

        # contact.db 提供私聊与群聊；消息分片补出联系人库里没有的 wxid_d。
        self.assertEqual(
            set(names),
            {"wxid_c", "222@chatroom", "wxid_d"},
        )
        # remark 优先于 nick_name。
        self.assertEqual(names["wxid_c"], "C备注")
        self.assertEqual(names["222@chatroom"], "群B")
        # 群成员没有自己的会话表，不能被误判成私聊。
        self.assertNotIn("wxid_group_member", names)

        flags = {item["username"]: item["has_messages"] for item in rows}
        self.assertTrue(flags["wxid_d"])
        self.assertFalse(flags["wxid_c"])

    def test_unresolved_md5_chat_is_ignored(self):
        md5_only = "a" * 32
        db = FakeDB(self.root)
        # 没有消息分片，只能走 list_message_chats() 兜底。
        db.message_chats = [
            {"md5": md5_only, "username": md5_only, "name": md5_only, "message_count": 9},
            {"md5": "b" * 32, "username": "wxid_real", "name": "真人", "message_count": 3},
        ]
        rows = self.core.list_contacts(db)
        self.assertEqual([item["username"] for item in rows], ["wxid_real"])

    def test_missing_contact_sources_do_not_raise(self):
        db = FakeDB(self.root)
        self.assertEqual(self.core.list_contacts(db), [])


class UniqueFolderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = load_core()

    def test_duplicate_names_get_stable_distinct_folders(self):
        used = set()
        first = self.core._unique_chat_folder("同名", "wxid_a", used)
        second = self.core._unique_chat_folder("同名", "wxid_b", used)
        self.assertEqual(first, "同名")
        self.assertNotEqual(first, second)
        self.assertIn("wxid_b", second)

    def test_long_names_keep_the_disambiguating_suffix(self):
        used = set()
        name = "很长的会话名字" * 30
        first = self.core._unique_chat_folder(name, "wxid_a", used)
        second = self.core._unique_chat_folder(name, "wxid_b", used)
        self.assertNotEqual(first, second)
        self.assertLessEqual(len(first), 100)
        self.assertLessEqual(len(second), 100)
        self.assertIn("wxid_b", second)


class ExportAllChatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = load_core()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.out = self.root / "output"

    def _result(self, kwargs, message_count=3):
        folder = kwargs["folder_name"]
        return {
            "chat_name": kwargs["contact"]["name"],
            "is_group": kwargs["contact"]["is_group"],
            "message_count": message_count,
            "sender_resolution_counts": {"resolved": message_count},
            "media_stats": {"images_requested": 0, "images_exported": 0},
            "output_dir": str(self.out / folder),
            "txt": str(self.out / folder / "chat_full_for_llm.txt"),
            "md": str(self.out / folder / "chat_full_for_llm.md"),
            "json": str(self.out / folder / "chat_full_parsed.json"),
        }

    def test_isolates_failures_and_writes_index(self):
        db = FakeDB(self.root, nicks={
            "wxid_zhang": "张三",
            "wxid_li": "李四",
            "123@chatroom": "群A",
        })
        seen = []

        def fake_impl(**kwargs):
            username = kwargs["contact"]["username"]
            seen.append(kwargs)
            if username == "wxid_li":
                raise ValueError("没有读取到该会话的消息。")
            if username == "123@chatroom":
                raise RuntimeError("synthetic failure")
            return self._result(kwargs)

        with (
            patch.object(self.core.tempfile, "gettempdir", return_value=str(self.root)),
            patch.object(self.core, "WeChatDB", return_value=db) as constructor,
            patch.object(self.core, "_export_chat_impl", side_effect=fake_impl),
        ):
            result = self.core.export_all_chats(str(self.out))

        # 整批只构造一次 WeChatDB，且所有会话共用同一个 db 与索引缓存。
        constructor.assert_called_once()
        self.assertEqual(len(seen), 3)
        self.assertIs(seen[0]["db"], seen[1]["db"])
        self.assertIs(seen[0]["index_cache"], seen[2]["index_cache"])

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["private_total"], 2)
        self.assertEqual(result["group_total"], 1)
        self.assertEqual(result["exported"], 1)
        self.assertEqual(result["skipped_empty"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["total_messages"], 3)
        self.assertTrue(result["sensitive_cache_cleanup"])

        # 敏感一次性工作目录必须已被清理。
        leftover = list(
            (self.root / "wechat-chat-export-sensitive").glob("run-*")
        ) if (self.root / "wechat-chat-export-sensitive").exists() else []
        self.assertEqual(leftover, [])

        data = json.loads(
            Path(result["index_json"]).read_text(encoding="utf-8-sig")
        )
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["exporter_version"], self.core.APP_VERSION)
        self.assertEqual(
            {item["username"]: item["status"] for item in data["chats"]},
            {
                "wxid_zhang": "exported",
                "wxid_li": "skipped_empty",
                "123@chatroom": "failed",
            },
        )
        markdown = Path(result["index_md"]).read_text(encoding="utf-8")
        self.assertIn("张三", markdown)
        self.assertIn("无消息", markdown)
        self.assertIn("失败", markdown)

    def test_duplicate_names_export_to_separate_folders(self):
        db = FakeDB(self.root, nicks={"wxid_a": "同名", "wxid_b": "同名"})

        def fake_impl(**kwargs):
            return self._result(kwargs, message_count=1)

        with (
            patch.object(self.core.tempfile, "gettempdir", return_value=str(self.root)),
            patch.object(self.core, "WeChatDB", return_value=db),
            patch.object(self.core, "_export_chat_impl", side_effect=fake_impl),
        ):
            result = self.core.export_all_chats(str(self.out))

        folders = [item["folder"] for item in result["chats"]]
        self.assertEqual(result["exported"], 2)
        self.assertEqual(len(set(folders)), 2)
        self.assertTrue(any("wxid" in folder for folder in folders))

    def test_limit_caps_exported_chats(self):
        db = FakeDB(self.root, nicks={
            "wxid_1": "一", "wxid_2": "二", "wxid_3": "三",
        })

        def fake_impl(**kwargs):
            return self._result(kwargs, message_count=1)

        with (
            patch.object(self.core.tempfile, "gettempdir", return_value=str(self.root)),
            patch.object(self.core, "WeChatDB", return_value=db),
            patch.object(self.core, "_export_chat_impl", side_effect=fake_impl),
        ):
            result = self.core.export_all_chats(str(self.out), limit=2)

        self.assertEqual(len(result["chats"]), 2)
        self.assertEqual(result["exported"], 2)
        self.assertTrue(result["limited"])
        # 上限只影响本次处理范围，不改变实际发现到的会话总数。
        self.assertEqual(result["private_total"], 3)

    def test_recent_sessions_are_processed_first(self):
        db = FakeDB(self.root, nicks={
            "wxid_new": "新会话",
            "wxid_old": "旧会话",
            "wxid_none": "从未聊过",
        })
        db.sessions = [
            {"username": "wxid_new", "unread": 0, "summary": "s",
             "last_time": 1700000000, "last_sender": ""},
            {"username": "wxid_old", "unread": 0, "summary": "s",
             "last_time": 1600000000, "last_sender": ""},
        ]
        seen = []

        def fake_impl(**kwargs):
            seen.append(kwargs["contact"]["username"])
            return self._result(kwargs, message_count=1)

        with (
            patch.object(self.core.tempfile, "gettempdir", return_value=str(self.root)),
            patch.object(self.core, "WeChatDB", return_value=db),
            patch.object(self.core, "_export_chat_impl", side_effect=fake_impl),
        ):
            result = self.core.export_all_chats(str(self.out), limit=2)

        # 有最近会话时间的排前面，没有记录的排最后。
        self.assertEqual(seen, ["wxid_new", "wxid_old"])
        self.assertTrue(result["limited"])
        self.assertEqual(result["total"], 2)
        # 会话总数与“其中有消息”是枚举期的事实，不受数量上限影响。
        self.assertEqual(result["private_total"], 3)
        markdown = Path(result["index_md"]).read_text(encoding="utf-8")
        self.assertIn("2023-11-1", markdown)

    def test_end_to_end_batch_export_writes_each_chat(self):
        """不 mock _export_chat_impl，验证真实批量链路的落盘结果。"""
        db = FakeDB(self.root, nicks={
            "wxid_self": "我",
            "wxid_zhang": "张三",
            "111@chatroom": "群A",
            "wxid_empty": "空会话",
        })
        shard = self.root / "message_0.db"
        make_full_shard(
            shard,
            {2: "wxid_zhang", 9: "wxid_self"},
            {
                "wxid_zhang": [{}, {"real_sender_id": 9}],
                "111@chatroom": [
                    {"real_sender_id": 2, "message_content": "wxid_zhang:\n群消息"},
                ],
            },
        )
        db.add_db("message/message_0.db", shard, shard=True)

        with (
            patch.object(self.core.tempfile, "gettempdir", return_value=str(self.root)),
            patch.object(self.core, "WeChatDB", return_value=db),
        ):
            result = self.core.export_all_chats(str(self.out))

        self.assertEqual(result["discovered_total"], 4)
        self.assertEqual(result["with_messages"], 2)
        # 从未有消息的联系人默认不逐个尝试。
        self.assertEqual(result["skipped_no_messages"], 2)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["exported"], 2)
        self.assertEqual(result["skipped_empty"], 0)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["total_messages"], 3)

        for item in result["chats"]:
            if item["status"] != "exported":
                continue
            folder = Path(item["output_dir"])
            self.assertTrue(folder.is_dir())
            for name in (
                "chat_full_for_llm.txt",
                "chat_full_for_llm.md",
                "chat_full_parsed.json",
            ):
                self.assertTrue((folder / name).is_file(), name)

        by_username = {item["username"]: item for item in result["chats"]}
        self.assertEqual(by_username["wxid_zhang"]["message_count"], 2)
        self.assertEqual(by_username["111@chatroom"]["message_count"], 1)
        # 群聊的 username 不在 Name2Id 里，但必须靠 Msg_<md5> 表被认定为“有消息”，
        # 否则默认跳过逻辑会把真实群聊漏掉。
        self.assertTrue(by_username["111@chatroom"]["has_messages"])
        self.assertNotIn("wxid_empty", by_username)
        self.assertNotIn("wxid_self", by_username)

        group_txt = Path(by_username["111@chatroom"]["txt"]).read_text(
            encoding="utf-8-sig"
        )
        # 群消息的发送者身份与正文前缀都要按已解析的发送者处理。
        self.assertIn("张三", group_txt)
        self.assertIn("群消息", group_txt)
        self.assertNotIn("wxid_zhang:", group_txt)

    def _two_contact_db(self):
        """一个真聊过的联系人 + 一个只加过好友的联系人。"""
        db = FakeDB(self.root, nicks={"wxid_with": "聊过", "wxid_without": "没聊过"})
        shard = self.root / "message_0.db"
        make_full_shard(shard, {2: "wxid_with"}, {"wxid_with": [{}]})
        db.add_db("message/message_0.db", shard, shard=True)
        return db

    def test_contacts_without_messages_are_skipped_by_default(self):
        db = self._two_contact_db()
        seen = []

        def fake_impl(**kwargs):
            seen.append(kwargs["contact"]["username"])
            return self._result(kwargs, message_count=1)

        with (
            patch.object(self.core.tempfile, "gettempdir", return_value=str(self.root)),
            patch.object(self.core, "WeChatDB", return_value=db),
            patch.object(self.core, "_export_chat_impl", side_effect=fake_impl),
        ):
            result = self.core.export_all_chats(str(self.out))

        self.assertEqual(seen, ["wxid_with"])
        self.assertEqual(result["discovered_total"], 2)
        self.assertEqual(result["with_messages"], 1)
        self.assertEqual(result["skipped_no_messages"], 1)
        self.assertEqual(result["total"], 1)

    def test_include_empty_attempts_contacts_without_messages(self):
        db = self._two_contact_db()
        seen = []

        def fake_impl(**kwargs):
            seen.append(kwargs["contact"]["username"])
            return self._result(kwargs, message_count=1)

        with (
            patch.object(self.core.tempfile, "gettempdir", return_value=str(self.root)),
            patch.object(self.core, "WeChatDB", return_value=db),
            patch.object(self.core, "_export_chat_impl", side_effect=fake_impl),
        ):
            result = self.core.export_all_chats(str(self.out), include_empty=True)

        self.assertEqual(sorted(seen), ["wxid_with", "wxid_without"])
        self.assertEqual(result["skipped_no_messages"], 0)
        self.assertEqual(result["total"], 2)

    def test_no_contacts_raises_clear_error(self):
        db = FakeDB(self.root)
        with (
            patch.object(self.core.tempfile, "gettempdir", return_value=str(self.root)),
            patch.object(self.core, "WeChatDB", return_value=db),
        ):
            with self.assertRaisesRegex(ValueError, "没有发现可导出的私聊或群聊"):
                self.core.export_all_chats(str(self.out))


class UpstreamSideEffectTests(unittest.TestCase):
    """上游依赖不能在工作目录留下日志等长期文件。"""

    @classmethod
    def setUpClass(cls):
        cls.core = load_core()

    def test_sandbox_mutes_and_restores_upstream_file_logger(self):
        class FakeParam:
            ENABLE_FILE_LOGGER = True

        param_module = ModuleType("wechatauto.param")
        param_module.WxParam = FakeParam

        with tempfile.TemporaryDirectory() as td:
            workdir = Path(td) / "run-test"
            workdir.mkdir()
            with patch.dict(sys.modules, {"wechatauto.param": param_module}):
                with self.core._upstream_sensitive_sandbox(workdir):
                    # 导出期间上游文件日志必须关闭，否则它会在当前工作目录
                    # 创建 wechatauto_logs/。
                    self.assertFalse(FakeParam.ENABLE_FILE_LOGGER)
                # 结束后恢复原值，不影响进程其余部分。
                self.assertTrue(FakeParam.ENABLE_FILE_LOGGER)

    def test_sandbox_tolerates_missing_upstream_param_module(self):
        with tempfile.TemporaryDirectory() as td:
            workdir = Path(td) / "run-test"
            workdir.mkdir()
            with patch.dict(sys.modules, {"wechatauto.param": None}):
                with self.core._upstream_sensitive_sandbox(workdir):
                    pass


if __name__ == "__main__":
    unittest.main()
