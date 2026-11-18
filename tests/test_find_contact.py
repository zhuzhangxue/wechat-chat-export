import hashlib
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_sender_mapping import load_export_modules  # noqa: E402


class ContactDB:
    """search_contact() 模拟上游的模糊匹配；消息表决定“本机有没有聊天记录”。"""

    def __init__(self, root: Path, contacts, chatted):
        self.contacts = contacts
        self.path = root / "message_0.db"
        with closing(sqlite3.connect(self.path)) as conn:
            for username in chatted:
                digest = hashlib.md5(username.encode("utf-8")).hexdigest()
                conn.execute(f'CREATE TABLE "Msg_{digest}" (local_id INTEGER)')
            conn.commit()

    def search_contact(self, keyword):
        out = []
        for c in self.contacts:
            fields = (c.get("nick_name"), c.get("remark"), c["username"], c.get("alias"))
            if any(keyword in (f or "") for f in fields):
                out.append({k: c.get(k) for k in ("username", "nick_name", "remark")})
        return out

    def _message_dbs(self):
        return ["message_0.db"]

    def _open(self, _rel):
        return sqlite3.connect(self.path)


class FindContactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core, _ = load_export_modules()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def db(self, contacts, chatted):
        return ContactDB(self.root, contacts, chatted)

    def test_unique_exact_remark_wins_over_fuzzy_matches(self):
        db = self.db([
            {"username": "wxid_a", "nick_name": "Zhang", "remark": "张三"},
            {"username": "wxid_b", "nick_name": "张三丰", "remark": ""},
        ], chatted=["wxid_a", "wxid_b"])
        self.assertEqual(self.core.find_contact(db, "张三")["username"], "wxid_a")

    def test_remark_tier_beats_nickname_tier(self):
        # 我给好友备注了“小王”，某个陌生群成员的昵称恰好也叫“小王”
        db = self.db([
            {"username": "wxid_friend", "nick_name": "Wang", "remark": "小王"},
            {"username": "wxid_stranger", "nick_name": "小王", "remark": ""},
        ], chatted=["wxid_friend", "wxid_stranger"])
        self.assertEqual(self.core.find_contact(db, "小王")["username"], "wxid_friend")

    def test_same_nickname_resolved_only_by_local_chat_existence(self):
        # 两个昵称都叫“李四”，其中一个只是群成员、本机没有私聊记录
        db = self.db([
            {"username": "wxid_member", "nick_name": "李四", "remark": ""},
            {"username": "wxid_li", "nick_name": "李四", "remark": ""},
        ], chatted=["wxid_li"])
        self.assertEqual(self.core.find_contact(db, "李四")["username"], "wxid_li")

    def test_same_nickname_both_with_chats_is_ambiguous_not_first_match(self):
        db = self.db([
            {"username": "wxid_1", "nick_name": "李四", "remark": ""},
            {"username": "wxid_2", "nick_name": "李四", "remark": ""},
        ], chatted=["wxid_1", "wxid_2"])
        with self.assertRaises(self.core.AmbiguousContactError) as ctx:
            self.core.find_contact(db, "李四")
        self.assertEqual({c["username"] for c in ctx.exception.candidates}, {"wxid_1", "wxid_2"})
        self.assertIn("wxid_1", str(ctx.exception))
        self.assertIn("wxid_2", str(ctx.exception))
        self.assertIn("多选导出", str(ctx.exception))

    def test_ambiguous_fuzzy_match_raises_instead_of_picking_first(self):
        db = self.db([
            {"username": "111@chatroom", "nick_name": "项目群A", "remark": ""},
            {"username": "222@chatroom", "nick_name": "项目群B", "remark": ""},
        ], chatted=["111@chatroom", "222@chatroom"])
        with self.assertRaises(self.core.AmbiguousContactError):
            self.core.find_contact(db, "项目")

    def test_single_fuzzy_match_with_chat_is_accepted(self):
        db = self.db([
            {"username": "111@chatroom", "nick_name": "项目群A", "remark": ""},
            {"username": "wxid_x", "nick_name": "项目经理", "remark": ""},
        ], chatted=["111@chatroom"])
        self.assertEqual(self.core.find_contact(db, "项目")["username"], "111@chatroom")

    def test_exact_username_is_always_unambiguous(self):
        db = self.db([
            {"username": "wxid_1", "nick_name": "李四", "remark": ""},
            {"username": "wxid_10", "nick_name": "李四", "remark": ""},
        ], chatted=["wxid_1", "wxid_10"])
        self.assertEqual(self.core.find_contact(db, "wxid_1")["username"], "wxid_1")

    def test_no_match_and_no_chat_errors(self):
        db = self.db([
            {"username": "wxid_1", "nick_name": "李四", "remark": ""},
            {"username": "wxid_2", "nick_name": "李四", "remark": ""},
        ], chatted=[])
        with self.assertRaises(ValueError) as ctx:
            self.core.find_contact(db, "李四")
        self.assertNotIsInstance(ctx.exception, self.core.AmbiguousContactError)
        self.assertIn("都没有聊天记录", str(ctx.exception))
        with self.assertRaises(ValueError):
            self.core.find_contact(db, "不存在")
        with self.assertRaises(ValueError):
            self.core.find_contact(db, "   ")

    def test_multi_select_records_ambiguous_keyword_as_not_found(self):
        db = self.db([
            {"username": "wxid_1", "nick_name": "李四", "remark": ""},
            {"username": "wxid_2", "nick_name": "李四", "remark": ""},
        ], chatted=["wxid_1", "wxid_2"])
        chats = [
            {"username": "wxid_1", "name": "李四", "is_group": False, "last_time": 1},
            {"username": "wxid_2", "name": "李四", "is_group": False, "last_time": 2},
        ]
        picked, missing = self.core._select_chats(db, chats, [], ["李四"], lambda _m: None)
        self.assertEqual(picked, [])
        self.assertEqual(missing[0]["query"], "李四")
        self.assertIn("无法确定", missing[0]["reason"])


if __name__ == "__main__":
    unittest.main()
