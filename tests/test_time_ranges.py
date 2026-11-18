import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import time_ranges as tr  # noqa: E402
from test_sender_mapping import FakeDB, load_export_modules  # noqa: E402


def ts(text):
    fmt = "%Y-%m-%d %H:%M:%S" if text.count(":") == 2 else "%Y-%m-%d %H:%M"
    return int(datetime.strptime(text, fmt).timestamp())


class ParseRangeLineTests(unittest.TestCase):
    def test_single_date_is_whole_day(self):
        r = tr.parse_range_line("2025-03-01")
        self.assertEqual(r.start, ts("2025-03-01 00:00"))
        self.assertEqual(r.end, ts("2025-03-02 00:00"))
        self.assertEqual(r.label, "2025-03-01")

    def test_date_range_includes_end_day(self):
        r = tr.parse_range_line("2025-03-01 ~ 2025-03-05")
        self.assertEqual(r.start, ts("2025-03-01 00:00"))
        self.assertEqual(r.end, ts("2025-03-06 00:00"))
        self.assertEqual(r.label, "2025-03-01 ~ 2025-03-05")

    def test_end_time_only_reuses_start_date_and_includes_that_minute(self):
        r = tr.parse_range_line("2025-03-01 14:00 ~ 16:30")
        self.assertEqual(r.start, ts("2025-03-01 14:00"))
        self.assertEqual(r.end, ts("2025-03-01 16:31"))
        self.assertTrue(r.contains(ts("2025-03-01 16:30:59")))
        self.assertFalse(r.contains(ts("2025-03-01 16:31:00")))
        self.assertEqual(r.label, "2025-03-01 14:00 ~ 2025-03-01 16:30")

    def test_seconds_precision(self):
        r = tr.parse_range_line("2025-03-01 14:00:05 ~ 14:00:10")
        self.assertEqual(r.end, ts("2025-03-01 14:00:11"))

    def test_open_ended(self):
        since = tr.parse_range_line("2025-03-01 ~")
        self.assertIsNone(since.end)
        self.assertTrue(since.contains(ts("2030-01-01 00:00")))
        until = tr.parse_range_line("~ 2025-03-05")
        self.assertIsNone(until.start)
        self.assertTrue(until.contains(1))
        self.assertFalse(until.contains(ts("2025-03-06 00:00")))

    def test_alternative_spellings(self):
        expected = tr.parse_range_line("2025-03-01 14:05 ~ 2025-03-01 18:00")
        for text in (
            "2025/3/1 14:05 至 2025/3/1 18:00",
            "2025.03.01 14：05 ～ 18:00",
            "2025年3月1日 14:05 到 2025年3月1日 18:00",
            "  2025-3-1   14:05~18:00  ",
        ):
            with self.subTest(text=text):
                got = tr.parse_range_line(text)
                self.assertEqual((got.start, got.end), (expected.start, expected.end))

    def test_invalid_lines(self):
        for text in (
            "2025-13-01",
            "2025-02-30",
            "2025-03-01 25:00 ~ 26:00",
            "2025-03-05 ~ 2025-03-01",
            "2025-03-01 14:00 ~ 13:00",
            "~",
            "14:00 ~ 15:00",
            "2025-03-01 14:00",
            "2025-03-01 ~ 2025-03-02 ~ 2025-03-03",
            "yesterday",
        ):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    tr.parse_range_line(text)


class ParseTimeRangesTests(unittest.TestCase):
    def test_empty_means_no_filter(self):
        self.assertEqual(tr.parse_time_ranges(None), [])
        self.assertEqual(tr.parse_time_ranges(""), [])
        self.assertEqual(tr.parse_time_ranges("\n  \n# 注释\n"), [])
        self.assertEqual(tr.parse_time_ranges([]), [])

    def test_multiline_sorted_and_merged(self):
        text = """
        # 群里我说话的几段
        2025-05-01 20:00 ~ 21:00
        2025-03-01 14:00 ~ 16:30
        2025-03-01 16:00 ~ 17:00
        2025-03-01 17:01 ~ 17:30
        2025-03-01 17:35 ~ 17:40
        2025-04-01；2025-04-02
        """
        ranges = tr.parse_time_ranges(text)
        # 14:00~16:30 与 16:00~17:00 重叠；“~17:00”包含 17:00 这一分钟，
        # 所以与 17:01 开始的段首尾相接，也合并；17:35 起的段与之有空隙，保持独立。
        self.assertEqual(
            [r.label for r in ranges],
            [
                "2025-03-01 14:00 ~ 2025-03-01 17:30",
                "2025-03-01 17:35 ~ 2025-03-01 17:40",
                "2025-04-01 ~ 2025-04-02",
                "2025-05-01 20:00 ~ 2025-05-01 21:00",
            ],
        )

    def test_contained_range_is_absorbed(self):
        ranges = tr.parse_time_ranges(["2025-03-01 ~ 2025-03-10", "2025-03-03 12:00 ~ 13:00"])
        self.assertEqual([r.label for r in ranges], ["2025-03-01 ~ 2025-03-10"])

    def test_open_ranges_merge(self):
        ranges = tr.parse_time_ranges("~ 2025-03-05\n2025-03-03 ~\n")
        self.assertEqual(len(ranges), 1)
        self.assertIsNone(ranges[0].start)
        self.assertIsNone(ranges[0].end)

    def test_all_errors_reported_with_position(self):
        with self.assertRaises(ValueError) as ctx:
            tr.parse_time_ranges("2025-03-01\nbad line\n2025-03-05 ~ 2025-03-01")
        message = str(ctx.exception)
        self.assertIn("第 2 个时间段", message)
        self.assertIn("第 3 个时间段", message)


class FilterRowsTests(unittest.TestCase):
    def test_keeps_rows_in_any_range_and_tags_index(self):
        ranges = tr.parse_time_ranges(
            "2025-03-01 14:00 ~ 15:00\n2025-03-02 09:00 ~ 10:00"
        )
        rows = [
            {"id": "before", "t": ts("2025-03-01 13:59:59")},
            {"id": "a", "t": ts("2025-03-01 14:00")},
            {"id": "a_end", "t": ts("2025-03-01 15:00:59")},
            {"id": "gap", "t": ts("2025-03-01 15:01")},
            {"id": "b", "t": ts("2025-03-02 09:30") * 1000},
            {"id": "missing", "t": 0},
        ]

        def get_ts(row):
            value = row["t"]
            return value // 1000 if value > 10_000_000_000 else value

        kept, unknown = tr.filter_rows_by_ranges(rows, ranges, get_ts)
        self.assertEqual([r["id"] for r in kept], ["a", "a_end", "b"])
        self.assertEqual([r["_range_index"] for r in kept], [1, 1, 2])
        self.assertEqual(unknown, 1)

    def test_no_ranges_keeps_everything(self):
        rows = [{"t": 0}, {"t": 5}]
        kept, unknown = tr.filter_rows_by_ranges(rows, [], lambda r: r["t"])
        self.assertEqual(kept, rows)
        self.assertEqual(unknown, 0)


class ExportWithRangesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core, _ = load_export_modules()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = FakeDB(self.root)
        self.db.add_shard({2: "wxid_target", 9: "wxid_self"}, [
            {"create_time": ts("2025-03-01 13:00"), "message_content": "noise-1"},
            {"create_time": ts("2025-03-01 14:10"), "message_content": "keep-1"},
            {"create_time": ts("2025-03-01 14:20"), "message_content": "keep-2"},
            {"create_time": ts("2025-03-01 18:00"), "message_content": "noise-2"},
            {"create_time": ts("2025-03-05 09:05"), "message_content": "keep-3"},
            {"create_time": ts("2025-03-06 09:05"), "message_content": "noise-3"},
        ])

    def export(self, time_ranges):
        logs = []
        with patch.object(self.core, "WeChatDB", return_value=self.db):
            result = self.core.export_chat(
                "Target remark",
                out_root=self.root / "output",
                progress=logs.append,
                time_ranges=time_ranges,
            )
        data = json.loads(Path(result["json"]).read_text(encoding="utf-8-sig"))
        return data, result, logs

    def test_multiple_ranges_export_only_matching_messages(self):
        data, result, logs = self.export(
            "2025-03-05 09:00 ~ 09:10\n2025-03-01 14:00 ~ 14:30\n"
        )
        self.assertEqual(
            [m["content"] for m in data["messages"]], ["keep-1", "keep-2", "keep-3"]
        )
        self.assertEqual([m["range_index"] for m in data["messages"]], [1, 1, 2])
        self.assertEqual(
            [r["label"] for r in data["time_ranges"]],
            ["2025-03-01 14:00 ~ 2025-03-01 14:30", "2025-03-05 09:00 ~ 2025-03-05 09:10"],
        )
        self.assertEqual(result["message_count"], 3)
        self.assertTrue(any("保留 3/6" in line for line in logs))

        txt = Path(result["txt"]).read_text(encoding="utf-8-sig")
        self.assertNotIn("noise", txt)
        self.assertIn("时间段 1/2", txt)
        self.assertIn("时间段 2/2", txt)
        self.assertIn("中间时段的消息未导出", txt)
        md = Path(result["md"]).read_text(encoding="utf-8")
        self.assertIn("时间段 2/2", md)
        self.assertNotIn("noise", md)

    def test_single_range_has_header_but_no_section_markers(self):
        data, result, _ = self.export("2025-03-01 ~ 2025-03-05")
        self.assertEqual(len(data["messages"]), 5)
        txt = Path(result["txt"]).read_text(encoding="utf-8-sig")
        self.assertIn("2025-03-01 ~ 2025-03-05", txt)
        self.assertNotIn("时间段 1/1", txt)

    def test_without_ranges_exports_everything_unchanged(self):
        data, result, _ = self.export(None)
        self.assertEqual(len(data["messages"]), 6)
        self.assertIsNone(data["time_ranges"])
        self.assertNotIn("range_index", data["messages"][0])
        txt = Path(result["txt"]).read_text(encoding="utf-8-sig")
        self.assertNotIn("导出时间段", txt)

    def test_no_messages_in_ranges_is_empty_conversation(self):
        with patch.object(self.core, "WeChatDB", return_value=self.db):
            with self.assertRaises(self.core.EmptyConversationError) as ctx:
                self.core.export_chat(
                    "Target remark", out_root=self.root / "output",
                    time_ranges="2030-01-01",
                )
        self.assertIn("2030-01-01", str(ctx.exception))

    def test_invalid_ranges_fail_before_touching_database(self):
        with patch.object(self.core, "WeChatDB") as constructor:
            with self.assertRaises(ValueError):
                self.core.export_chat(
                    "Target remark", out_root=self.root, time_ranges="bad"
                )
        constructor.assert_not_called()

    def test_batch_passes_ranges_and_records_them(self):
        chats = [{
            "username": "wxid_target", "name": "Target",
            "is_group": False, "last_time": None,
        }]
        seen = []

        def fake_impl(**kwargs):
            seen.append(kwargs.get("time_ranges"))
            raise self.core.EmptyConversationError("none")

        with patch.object(self.core, "WeChatDB", return_value=self.db), \
                patch.object(self.core, "_batch_chat_candidates", return_value=(chats, 0)), \
                patch.object(self.core, "_export_chat_impl", side_effect=fake_impl):
            result = self.core.export_all_chats(
                self.root / "batch", time_ranges=["2025-03-01", "2025-04-01 ~ 2025-04-03"],
            )
        self.assertEqual(len(seen[0]), 2)
        self.assertEqual(
            [r["label"] for r in result["time_ranges"]],
            ["2025-03-01", "2025-04-01 ~ 2025-04-03"],
        )
        self.assertEqual(result["skipped_empty"], 1)
        index_md = Path(result["index_md"]).read_text(encoding="utf-8")
        self.assertIn("2025-04-01 ~ 2025-04-03", index_md)


if __name__ == "__main__":
    unittest.main()
