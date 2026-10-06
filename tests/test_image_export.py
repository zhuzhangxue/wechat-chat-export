import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
IMAGE_HASH = "0123456789abcdef0123456789abcdef"


def load_core():
    wechatauto = ModuleType("wechatauto")
    wechatauto.WeChatDB = Mock()
    wechatauto.MediaDownloader = Mock()
    zstandard = ModuleType("zstandard")
    zstandard.ZstdDecompressor = Mock()
    pillow = ModuleType("PIL")
    pillow.Image = Mock()
    pillow.ImageStat = Mock()
    with patch.dict(sys.modules, {
        "wechatauto": wechatauto, "zstandard": zstandard, "PIL": pillow,
    }):
        spec = importlib.util.spec_from_file_location(
            "_image_export_exporter_core", ROOT / "exporter_core.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class ImageExportTests(unittest.TestCase):
    def setUp(self):
        self.core = load_core()

    def _run(self, image_index):
        md = Mock()
        md.decrypt_image.return_value = b"\xff\xd8\xff" + b"jpeg-payload"
        row = {"local_id": 7, "sort_seq": 99, "create_time": 1700000000}
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "images"
            with (
                patch.object(self.core, "_resource_image_hash", return_value=IMAGE_HASH),
                patch.object(self.core, "_find_plain_thumbnail", return_value=None),
            ):
                media, reason = self.core._write_image_from_row(
                    object(), md, row, "wxid_target", image_index, out,
                    ("0123456789abcdef", 0x88),
                )
            call_path = Path(md.decrypt_image.call_args.args[0])
            payload = Path(media["path"]).read_bytes()
            return reason, call_path, media["variant"], Path(media["path"]).name, payload

    def test_h_dat_is_preferred_over_plain_dat(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            normal = root / f"{IMAGE_HASH}.dat"
            high = root / f"{IMAGE_HASH}_h.dat"
            normal.write_bytes(b"normal")
            high.write_bytes(b"high")
            result = self._run({normal.name.lower(): normal, high.name.lower(): high})
        reason, call_path, variant, name, payload = result
        self.assertIsNone(reason)
        self.assertEqual(call_path, high)
        self.assertEqual(variant, "high")
        self.assertIn("_high.jpg", name)
        self.assertTrue(payload.startswith(b"\xff\xd8\xff"))

    def test_plain_dat_is_fallback_when_h_dat_is_absent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            normal = root / f"{IMAGE_HASH}.dat"
            normal.write_bytes(b"normal")
            result = self._run({normal.name.lower(): normal})
        reason, call_path, variant, name, payload = result
        self.assertIsNone(reason)
        self.assertEqual(call_path, normal)
        self.assertEqual(variant, "original")
        self.assertNotIn("_high", name)
        self.assertTrue(payload.startswith(b"\xff\xd8\xff"))


if __name__ == "__main__":
    unittest.main()
