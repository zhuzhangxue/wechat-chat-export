import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
VIDEO_ID = "1297d61b1db2a4eaa2fe8ca0cff19771"

FINDER_XML = f"""<msg>
<appmsg>
  <title>当前微信版本不支持展示该内容，请升级至最新版本。</title>
  <type>51</type>
  <url>https://support.weixin.qq.com/security/readtemplate?t=upgrade</url>
  <finderFeed>
    <objectId>13626785778503063620</objectId>
    <objectNonceId>814975960724467271_8_18_9</objectNonceId>
    <feedType>4</feedType>
    <nickname>测试视频号</nickname>
    <username>v2_test@finder</username>
    <desc>一条用于回归测试的视频号分享</desc>
    <mediaCount>1</mediaCount>
    <mediaList>
      <media>
        <mediaType>4</mediaType>
        <url><![CDATA[https://wxapp.example/stodownload?m={VIDEO_ID}&idx=1]]></url>
        <thumbUrl><![CDATA[https://wxapp.example/thumb.jpg]]></thumbUrl>
        <fullCoverUrl><![CDATA[https://wxapp.example/cover.jpg]]></fullCoverUrl>
        <width>896.0</width>
        <height>1920.0</height>
        <videoPlayDuration>34</videoPlayDuration>
      </media>
    </mediaList>
  </finderFeed>
</appmsg>
</msg>"""


def load_core():
    wechatauto = ModuleType("wechatauto")
    wechatauto.WeChatDB = Mock(
        side_effect=AssertionError("Real WeChatDB is forbidden")
    )
    wechatauto.MediaDownloader = Mock(
        side_effect=AssertionError("Media is forbidden")
    )

    zstandard = ModuleType("zstandard")
    zstandard.ZstdDecompressor = Mock(
        side_effect=AssertionError("No compressed fixtures")
    )

    pillow = ModuleType("PIL")
    pillow.Image = Mock()
    pillow.ImageStat = Mock()

    with patch.dict(sys.modules, {
        "wechatauto": wechatauto,
        "zstandard": zstandard,
        "PIL": pillow,
    }):
        spec = importlib.util.spec_from_file_location(
            "_video_channel_exporter_core",
            ROOT / "exporter_core.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class VideoChannelTests(unittest.TestCase):
    def setUp(self):
        self.core = load_core()

    def test_appmsg_type_51_is_rendered_as_video_channel(self):
        text = self.core.parse_app_message(FINDER_XML)
        self.assertEqual(
            text,
            "[视频号] 测试视频号：一条用于回归测试的视频号分享",
        )

    def test_finder_feed_metadata_is_preserved(self):
        info = self.core._parse_finder_feed(FINDER_XML)
        self.assertIsNotNone(info)
        self.assertEqual(info["appmsg_type"], "51")
        self.assertEqual(info["object_id"], "13626785778503063620")
        self.assertEqual(info["nickname"], "测试视频号")
        self.assertEqual(info["desc"], "一条用于回归测试的视频号分享")
        self.assertEqual(info["media"][0]["media_type"], "4")
        self.assertIn(VIDEO_ID, info["media"][0]["url"])
        self.assertEqual(info["media"][0]["video_play_duration"], "34")

    def test_microvideo_type_62_is_treated_as_video(self):
        self.assertEqual(self.core.parse_content(62, ""), "[视频]")

    def test_video_id_collection_uses_finder_media_url(self):
        row = {"message_content": FINDER_XML}
        finder = self.core._finder_feed_from_row(row)
        ids = self.core._collect_video_ids(row, finder_feed=finder)
        self.assertGreaterEqual(len(ids), 1)
        self.assertEqual(ids[0], VIDEO_ID)

    def test_chat_attach_raw_video_can_be_matched_and_exported(self):
        username = "wxid_target"
        chat_md5 = hashlib.md5(username.encode("utf-8")).hexdigest()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            account = root / "account"
            source_dir = (
                account
                / "msg"
                / "attach"
                / chat_md5
                / "2026-09"
                / "Video"
            )
            source_dir.mkdir(parents=True)
            source = source_dir / f"{VIDEO_ID}_raw.mp4"
            source.write_bytes(b"synthetic mp4 payload")

            db = SimpleNamespace(account_dir=str(account))
            index = self.core._index_video_files(db, username)
            self.assertEqual(index["count"], 1)
            self.assertIn(VIDEO_ID, index["by_stem"])

            output = root / "output"
            row = {
                "local_id": 7,
                "sort_seq": 8,
                "create_time": 1789056000,
                "message_content": FINDER_XML,
                "packed_info_data": None,
                "compress_content": None,
                "source": None,
            }
            finder = self.core._finder_feed_from_row(row)
            media, reason = self.core._write_video_from_row(
                row,
                index,
                output,
                finder_feed=finder,
            )

            self.assertIsNone(reason)
            self.assertIsNotNone(media)
            self.assertEqual(media["source"], "finder_feed")
            self.assertEqual(media["matched_id"], VIDEO_ID)
            self.assertEqual(media["source_variant"], "raw")
            exported = Path(media["path"])
            self.assertTrue(exported.is_file())
            self.assertEqual(exported.read_bytes(), b"synthetic mp4 payload")

    def test_missing_channel_cache_is_explicit_and_never_guessed(self):
        row = {
            "message_content": FINDER_XML,
            "packed_info_data": None,
            "compress_content": None,
            "source": None,
        }
        finder = self.core._finder_feed_from_row(row)
        media, reason = self.core._write_video_from_row(
            row,
            {"by_stem": {}, "count": 0},
            Path("unused"),
            finder_feed=finder,
        )
        self.assertIsNone(media)
        self.assertIn("视频号信息已解析", reason)
        self.assertIn("本地只读导出无法获得与视频 URL 配对的解密信息", reason)
        self.assertIn("不会自动联网下载或猜测缓存文件", reason)


if __name__ == "__main__":
    unittest.main()
