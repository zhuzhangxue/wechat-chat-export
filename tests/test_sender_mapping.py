import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import closing
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SELF_LABEL = "\u6211"
UNKNOWN_LABEL = "\u672a\u77e5\u53d1\u9001\u8005"


def load_export_modules():
    # Import the complete production modules, but prohibit real WeChat/media use.
    wechatauto = ModuleType("wechatauto")
    wechatauto.WeChatDB = Mock(side_effect=AssertionError("Real WeChatDB is forbidden"))
    wechatauto.MediaDownloader = Mock(side_effect=AssertionError("Media is forbidden"))
    zstandard = ModuleType("zstandard")
    zstandard.ZstdDecompressor = Mock(side_effect=AssertionError("No compressed fixtures"))
    pillow = ModuleType("PIL")
    pillow.Image = Mock()
    pillow.ImageStat = Mock()
    pillow.ImageTk = Mock()
    modules = []
    with patch.dict(sys.modules, {
        "wechatauto": wechatauto, "zstandard": zstandard, "PIL": pillow,
    }):
        for name in ("exporter_core", "preview"):
            spec = importlib.util.spec_from_file_location(
                "_sender_tests_" + name, ROOT / (name + ".py"),
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            modules.append(module)
    return modules


class FakeDB:
    def __init__(self, root, username="wxid_target", self_username="wxid_self"):
        self.root = root
        self.target = {"username": username, "nick_name": "Target", "remark": "Target remark"}
        self.self_info = {"username": self_username, "nick_name": "Self nickname"}
        self.account = "wxid_self_ab12"
        self.nicks = {
            "wxid_self": "Self remark", "wxid_target": "Target remark",
            "wxid_other": "Unrelated contact", "wxid_member": "Group member",
        }
        self.shards = {}
        self.opens = Counter()
        self.queries = []
        self.deny_sender_reads = False

    def _message_dbs(self):
        return list(self.shards)

    def _open(self, rel):
        self.opens[rel] += 1
        conn = sqlite3.connect(self.shards[rel].as_uri() + "?mode=ro", uri=True)
        conn.set_trace_callback(lambda sql: self.queries.append((rel, sql)))
        if self.deny_sender_reads:
            conn.set_authorizer(
                lambda action, table, column, database, trigger:
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_READ and table.lower() == "name2id"
                else sqlite3.SQLITE_OK
            )
        return conn

    def _sender_id_index(self):
        raise AssertionError("Global resource sender mapping must not be used")

    def _resolve_sender(self, *args):
        raise AssertionError("Legacy nickname/ID-based resolution must not be used")

    def search_contact(self, keyword):
        return [self.target.copy()]

    def get_self_info(self):
        return self.self_info.copy()

    def _nickname_index(self):
        return self.nicks.copy()

    def add_shard(self, names, messages, schema="normal"):
        path = self.root / ("message_" + str(len(self.shards)) + ".db")
        rel = "message\\" + path.name
        self.shards[rel] = path
        table = "Msg_" + hashlib.md5(self.target["username"].encode("utf-8")).hexdigest()
        with closing(sqlite3.connect(path)) as conn:
            if schema == "normal":
                conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
                conn.executemany("INSERT INTO Name2Id (rowid, user_name) VALUES (?, ?)", names.items())
            elif schema == "unsupported":
                conn.execute("CREATE TABLE Name2Id (different_column TEXT)")
            elif schema != "missing":
                raise AssertionError(schema)
            conn.execute(
                f"CREATE TABLE {table} (local_id INTEGER, local_type INTEGER, "
                "server_id INTEGER, real_sender_id, create_time INTEGER, "
                "message_content TEXT, compress_content TEXT, sort_seq INTEGER)"
            )
            for index, message in enumerate(messages, 1):
                row = {
                    "local_id": index, "local_type": 1, "server_id": 1000 + index,
                    "real_sender_id": 2, "create_time": 1700000000 + index,
                    "message_content": "Synthetic message", "compress_content": None,
                    "sort_seq": index,
                }
                row.update(message)
                conn.execute(
                    f"INSERT INTO {table} ({', '.join(row)}) "
                    f"VALUES ({', '.join('?' for _ in row)})", tuple(row.values()),
                )
            conn.commit()
        return rel


class SenderMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core, cls.preview = load_export_modules()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = FakeDB(self.root)

    def export(self):
        logs = []
        with patch.object(self.core, "WeChatDB", return_value=self.db) as constructor:
            result = self.core.export_chat(
                "Target remark", out_root=self.root / "output", progress=logs.append,
            )
        constructor.assert_called_once()
        call_kwargs = constructor.call_args.kwargs
        self.assertIsNone(call_kwargs["db_dir"])
        self.assertFalse(Path(call_kwargs["workdir"]).exists())
        data = json.loads(Path(result["json"]).read_text(encoding="utf-8-sig"))
        self.assertEqual(data["message_count"], len(data["messages"]))
        self.assertEqual(data["sender_resolution_counts"], result["sender_resolution_counts"])
        return data, result, logs

    def test_shard_local_ids_override_resource_table_and_id_two_is_not_self(self):
        with closing(sqlite3.connect(self.root / "message_resource.db")) as conn:
            conn.execute("CREATE TABLE SenderName2Id (user_name TEXT)")
            conn.execute("INSERT INTO SenderName2Id (rowid, user_name) VALUES (2, 'wxid_other')")
            conn.commit()
        first = self.db.add_shard({2: "wxid_target", 9: "wxid_self"}, [
            {"real_sender_id": 2}, {"real_sender_id": 9},
        ])
        second = self.db.add_shard({2: "wxid_self", 9: "wxid_target"}, [
            {"real_sender_id": "2", "sort_seq": 3},
            {"real_sender_id": "009", "sort_seq": 4},
        ])
        data, _, _ = self.export()
        messages = data["messages"]
        self.assertEqual([m["sender"] for m in messages], [
            "Target remark", SELF_LABEL, SELF_LABEL, "Target remark",
        ])
        self.assertEqual([m["is_self"] for m in messages], [False, True, True, False])
        self.assertEqual([m["source_db"] for m in messages], [first, first, second, second])
        self.assertEqual([m["real_sender_id"] for m in messages], [2, 9, "2", "009"])
        self.assertEqual([m["server_id"] for m in messages], [1001, 1002, 1001, 1002])
        self.assertEqual(self.db.opens, {first: 1, second: 1})
        map_queries = Counter(rel for rel, sql in self.db.queries
                              if sql == "SELECT rowid, user_name FROM Name2Id")
        self.assertEqual(map_queries, {first: 1, second: 1})
        self.assertEqual(data["sender_resolution_counts"], {"resolved": 4})

    def test_matching_nicknames_do_not_define_identity(self):
        self.db.target.update(remark="", nick_name="Same nickname")
        self.db.self_info["nick_name"] = "Same nickname"
        self.db.nicks.update(wxid_target="Same nickname", wxid_self="Different self remark")
        self.db.add_shard({2: "wxid_target", 8: "wxid_self"}, [
            {}, {"real_sender_id": 8},
        ])
        messages = self.export()[0]["messages"]
        self.assertEqual([m["sender"] for m in messages], ["Same nickname", SELF_LABEL])
        self.assertEqual([m["sender_username"] for m in messages], ["wxid_target", "wxid_self"])
        self.assertEqual([m["is_self"] for m in messages], [False, True])

    def test_numeric_id_validation(self):
        for value, expected in [(2, 2), ("2", 2), ("0002", 2), ("0" * 40 + "2", 2)]:
            with self.subTest(value=value):
                self.assertEqual(self.core._sender_id(value), expected)
        for value in [None, "", "bad", "2.0", "+2", " 2", "\u0662", True,
                      False, 2.0, b"2", -2, 0, 2 ** 63, "9" * 5000]:
            with self.subTest(value=repr(value)[:40]):
                self.assertIsNone(self.core._sender_id(value))

    def test_contact_named_me_is_not_displayed_as_self(self):
        self.db.target.update(remark=SELF_LABEL, nick_name=SELF_LABEL)
        self.db.self_info["nick_name"] = SELF_LABEL
        self.db.add_shard({2: "wxid_target", 9: "wxid_self"}, [
            {}, {"real_sender_id": 9},
        ])
        messages = self.export()[0]["messages"]
        self.assertEqual(messages[0]["sender"], SELF_LABEL + "\uff08wxid_target\uff09")
        self.assertIs(messages[0]["is_self"], False)
        self.assertEqual(messages[1]["sender"], SELF_LABEL)
        self.assertIs(messages[1]["is_self"], True)

    def test_invalid_and_unmapped_ids_never_guess_target(self):
        self.db.add_shard({2: "wxid_target", 3: ""}, [
            {"real_sender_id": sid} for sid in (None, "bad", 2.0, 0, -1, 77, 3)
        ])
        data, _, logs = self.export()
        self.assertTrue(all(m["sender"] == UNKNOWN_LABEL for m in data["messages"]))
        self.assertTrue(all(m["sender_username"] is None for m in data["messages"]))
        self.assertTrue(all(m["is_self"] is None for m in data["messages"]))
        self.assertEqual(data["sender_resolution_counts"], {
            "invalid_sender_id": 5, "unmapped_sender_id": 1, "invalid_sender_username": 1,
        })
        self.assertTrue(any("7/7" in log and "sender_status" in log for log in logs))

    def test_binary_sender_id_is_unknown_and_traceable_in_json(self):
        self.db.add_shard({2: "wxid_target"}, [{"real_sender_id": b"2"}])
        message = self.export()[0]["messages"][0]
        self.assertEqual(message["sender"], UNKNOWN_LABEL)
        self.assertEqual(message["sender_status"], "invalid_sender_id")
        self.assertEqual(message["real_sender_id"], {"encoding": "hex", "value": "32"})

    def test_missing_and_unsupported_maps_are_explicit(self):
        self.db.add_shard({}, [{}], schema="missing")
        self.db.add_shard({}, [{"sort_seq": 2}], schema="unsupported")
        data, _, logs = self.export()
        self.assertEqual(data["sender_resolution_counts"], {
            "missing_name2id": 1, "unsupported_name2id": 1,
        })
        self.assertTrue(all(m["sender"] == UNKNOWN_LABEL for m in data["messages"]))
        self.assertTrue(any("2/2" in log and "Name2Id" in log for log in logs))

    def test_sqlite_query_errors_propagate(self):
        self.db.add_shard({2: "wxid_target"}, [{}])
        self.db.deny_sender_reads = True
        with self.assertRaises(sqlite3.DatabaseError):
            self.export()
        self.assertFalse((self.root / "output").exists())

    def test_private_third_party_is_flagged_and_stable_id_preserved(self):
        self.db.add_shard({2: "wxid_other"}, [{}, {"sort_seq": 2}])
        data, _, logs = self.export()
        for message in data["messages"]:
            self.assertTrue(message["sender"].startswith(UNKNOWN_LABEL))
            self.assertNotIn("Unrelated contact", message["sender"])
            self.assertEqual(message["sender_username"], "wxid_other")
            self.assertIs(message["is_self"], False)
            self.assertEqual(message["sender_status"], "unexpected_private_sender")
        self.assertEqual(data["sender_resolution_counts"], {"unexpected_private_sender": 2})
        self.assertTrue(any("2/2" in log for log in logs))
        self.assertFalse(any("wxid_other" in log or "Synthetic message" in log for log in logs))

    def test_missing_self_username_never_guesses_from_nickname_or_account(self):
        self.db.self_info = {"nick_name": "Self remark"}
        self.db.add_shard({2: "wxid_target", 8: "wxid_self"}, [
            {}, {"real_sender_id": 8},
        ])
        data, _, logs = self.export()
        self.assertEqual(data["messages"][0]["sender"], "Target remark")
        self.assertTrue(data["messages"][1]["sender"].startswith(UNKNOWN_LABEL))
        self.assertTrue(all(m["is_self"] is None for m in data["messages"]))
        self.assertEqual(data["sender_resolution_counts"], {"self_unknown": 2})
        self.assertTrue(any("username" in log for log in logs))

    def test_self_username_is_normalized_upstream_and_compared_exactly(self):
        self.db.add_shard({2: "wxid_self", 3: "wxid_self_extra"}, [
            {}, {"real_sender_id": 3},
        ])
        messages = self.export()[0]["messages"]
        self.assertEqual(messages[0]["sender"], SELF_LABEL)
        self.assertEqual(messages[1]["sender_status"], "unexpected_private_sender")
        self.assertEqual(messages[1]["sender_username"], "wxid_self_extra")
        self.assertIs(messages[1]["is_self"], False)

    def test_group_members_and_verified_prefixes_are_preserved(self):
        self.db.target["username"] = "synthetic@chatroom"
        self.db.nicks["wxid_member"] = self.db.self_info["nick_name"]
        self.db.add_shard({2: "wxid_member", 9: "wxid_self", 7: "wxid_other"}, [
            {"message_content": "wxid_member:\nGroup message"},
            {"real_sender_id": 9, "message_content": "wxid_self: Own message"},
            {"real_sender_id": 7, "message_content": "Unprefixed message"},
            {"message_content": "", "compress_content": "wxid_member:\nLong message"},
        ])
        messages = self.export()[0]["messages"]
        self.assertEqual([m["sender"] for m in messages], [
            "Self nickname", SELF_LABEL, "Unrelated contact", "Self nickname",
        ])
        self.assertEqual([m["content"] for m in messages], [
            "Group message", "Own message", "Unprefixed message", "Long message",
        ])
        self.assertEqual([m["is_self"] for m in messages], [False, True, False, False])

    def test_unverified_group_prefixes_do_not_change_identity_or_text(self):
        self.db.target["username"] = "synthetic@chatroom"
        texts = ["wxid_other: ordinary text", "wxid_member:\nUnknown sender"]
        self.db.add_shard({2: "wxid_member"}, [
            {"message_content": texts[0]},
            {"real_sender_id": 99, "message_content": texts[1]},
        ])
        messages = self.export()[0]["messages"]
        self.assertEqual([m["content"] for m in messages], texts)
        self.assertEqual(messages[0]["sender_username"], "wxid_member")
        self.assertEqual(messages[1]["sender"], UNKNOWN_LABEL)
        self.assertIsNone(messages[1]["sender_username"])

    def test_system_quote_and_forward_content_stays_in_content(self):
        quote = ("<msg><appmsg><type>57</type><title>Reply</title><refermsg>"
                 "<displayname>Quoted alias</displayname><content>Quoted text</content>"
                 "<type>1</type></refermsg></appmsg></msg>")
        forward = ("<msg><appmsg><type>19</type><title>Forwarded chat</title>"
                   "<des>Another alias: forwarded text</des></appmsg></msg>")
        system = "wxid_other: system notice"
        self.db.add_shard({2: "wxid_target", 9: "wxid_other"}, [
            {"local_type": 49, "message_content": quote},
            {"local_type": 49, "message_content": forward},
            {"real_sender_id": 9, "local_type": 10000, "message_content": system},
        ])
        data, _, _ = self.export()
        for message, content, code in zip(data["messages"], [quote, forward, system], [49, 49, 10000]):
            self.assertEqual(message["content"], self.core.parse_content(code, content))
        self.assertEqual(data["messages"][2]["sender_status"], "system")
        self.assertIsNone(data["messages"][2]["is_self"])
        self.assertEqual(data["sender_resolution_counts"], {"resolved": 2, "system": 1})

    def test_json_txt_markdown_and_preview_use_same_sender(self):
        self.db.add_shard({2: "wxid_target", 9: "wxid_self"}, [
            {}, {"real_sender_id": 9},
        ])
        data, result, _ = self.export()
        txt = Path(result["txt"]).read_text(encoding="utf-8-sig")
        markdown = Path(result["md"]).read_text(encoding="utf-8")
        preview = SimpleNamespace(text=Mock(), _insert_separator=Mock())
        existing = {"local_id", "type", "type_code", "sender", "time", "content",
                    "sort_seq", "transcript", "transcript_source", "media"}
        for message in data["messages"]:
            self.assertTrue(existing.issubset(message))
            self.assertIn(f" | {message['sender']}\uff1a", txt)
            self.assertIn(f" | {message['sender']}\uff1a", markdown)
            self.preview.ChatPreview._render_message(preview, message)
        sender_lines = [call.args[1] for call in preview.text.insert.call_args_list
                        if call.args[2] == "sender"]
        self.assertEqual(sender_lines, [
            f"{message['time'][11:19]} | {message['sender']}\n"
            for message in data["messages"]
        ])


if __name__ == "__main__":
    unittest.main()
