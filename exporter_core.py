# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
import shutil
import tempfile
import subprocess
import sys
import tarfile
import unicodedata
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

import zstandard as zstd
from wechatauto import MediaDownloader, WeChatDB
from PIL import Image, ImageStat

APP_VERSION = "1.3.0"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

TYPE_LABEL = {
    1: "文本",
    3: "图片",
    34: "语音",
    43: "视频",
    47: "动画表情",
    48: "位置",
    49: "文件/链接/卡片",
    10000: "系统消息",
}


def safe_folder_name(name: str) -> str:
    name = (name or "未命名会话").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")
    if not name:
        name = "未命名会话"
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if name.upper() in reserved:
        name = "_" + name
    return name[:100]


def safe_file_name(name: str, fallback="file") -> str:
    name = Path(name or fallback).name.strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")
    if not name:
        name = fallback
    stem = Path(name).stem[:120] or fallback
    suffix = Path(name).suffix[:20]
    result = stem + suffix
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if Path(result).stem.upper() in reserved:
        result = "_" + result
    return result


def low_type(t):
    if isinstance(t, int) and t > 0xFFFF:
        return t & 0xFF
    return t


def decompress_zstd(data: bytes) -> bytes:
    with zstd.ZstdDecompressor().stream_reader(io.BytesIO(data)) as reader:
        return reader.read()


def decode_blob(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.replace("\x00", "").strip()
    if not isinstance(value, (bytes, bytearray)):
        return str(value).strip()

    data = bytes(value)
    if data.startswith(ZSTD_MAGIC):
        try:
            data = decompress_zstd(data)
        except Exception:
            return ""

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="ignore")

    text = text.replace("\x00", "").strip()
    positions = [
        p for p in (text.find("<msg"), text.find("<appmsg"), text.find("<sysmsg"))
        if p >= 0
    ]
    if positions:
        text = text[min(positions):]
    return text.strip()


def clean_text(s: str) -> str:
    s = html.unescape(s or "")
    return s.replace("\r\n", "\n").replace("\r", "\n").strip()


def xml_root(text: str):
    if not text or "<" not in text:
        return None
    candidate = text.strip()
    starts = [
        p for p in (
            candidate.find("<msg"),
            candidate.find("<appmsg"),
            candidate.find("<sysmsg"),
        )
        if p >= 0
    ]
    if starts:
        candidate = candidate[min(starts):]

    endings = []
    for closing in ("</msg>", "</appmsg>", "</sysmsg>"):
        idx = candidate.rfind(closing)
        if idx >= 0:
            endings.append(idx + len(closing))
    if endings:
        candidate = candidate[:max(endings)]

    try:
        return ET.fromstring(candidate)
    except Exception:
        return None


def parse_app_message(text: str) -> str:
    root = xml_root(text)
    if root is None:
        plain = re.sub(r"<[^>]+>", " ", text or "")
        plain = re.sub(r"\s+", " ", html.unescape(plain)).strip()
        return plain if plain else "[文件/链接/卡片]"

    appmsg = root if root.tag == "appmsg" else root.find("appmsg")
    if appmsg is None:
        appmsg = root.find(".//appmsg")
    if appmsg is None:
        return "[文件/链接/卡片]"

    app_type = clean_text(appmsg.findtext("type") or "")
    title = clean_text(appmsg.findtext("title") or "")
    desc = clean_text(appmsg.findtext("des") or "")
    url = clean_text(appmsg.findtext("url") or "")

    # 引用回复
    if app_type == "57":
        refer = appmsg.find("refermsg")
        if refer is None:
            refer = appmsg.find(".//refermsg")
        ref_name = (
            clean_text(refer.findtext("displayname") or "")
            if refer is not None else ""
        )
        ref_content = (
            clean_text(refer.findtext("content") or "")
            if refer is not None else ""
        )
        ref_type = (
            clean_text(refer.findtext("type") or "")
            if refer is not None else ""
        )

        if not ref_content:
            ref_content = "[原引用内容未解析]"
        elif ref_type and ref_type != "1" and ref_content.startswith("<"):
            ref_content = f"[被引用消息 type={ref_type}]"

        reply = title or desc or "[引用回复]"
        return f"{reply}\n    ↳ 引用 {ref_name or '对方'}：{ref_content}"

    if app_type == "6":
        return f"[文件] {title}".strip()

    if url:
        if title and desc:
            return f"[链接] {title}｜{desc}"
        if title:
            return f"[链接] {title}"
        return "[链接]"

    if title and desc:
        return f"[卡片] {title}｜{desc}"
    if title:
        return f"[卡片] {title}"
    if desc:
        return f"[卡片] {desc}"
    return "[文件/链接/卡片]"


def parse_system_message(text: str) -> str:
    text = clean_text(text)
    if not text:
        return "[系统消息]"

    if "<sysmsg" in text and "revokemsg" in text:
        root = xml_root(text)
        if root is not None:
            content = clean_text(root.findtext(".//revokemsg/content") or "")
            if content:
                return f"[撤回] {content}"
        m = re.search(r"<content>(.*?)</content>", text, re.S)
        if m:
            content = clean_text(
                re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1))
            )
            if content:
                return f"[撤回] {content}"
        return "[撤回了一条消息]"

    if "<sysmsg" in text:
        root = xml_root(text)
        if root is not None:
            for xpath in (".//content", ".//title", ".//tips"):
                value = clean_text(root.findtext(xpath) or "")
                if value:
                    return f"[系统] {value}"
        plain = re.sub(r"<[^>]+>", " ", text)
        plain = re.sub(r"\s+", " ", html.unescape(plain)).strip()
        return f"[系统] {plain}" if plain else "[系统消息]"

    return f"[系统] {text}"


GROUP_PREFIX_RE = re.compile(r"^(wxid_[0-9A-Za-z_-]+|[^:\r\n]+@chatroom):\s*")


def strip_group_prefix(text: str):
    """群文本常见形态：wxid_xxx: 正文。返回 (发送者wxid, 去前缀正文)。"""
    if not text:
        return "", text
    m = GROUP_PREFIX_RE.match(text)
    if not m:
        return "", text
    return m.group(1), text[m.end():]


def parse_content(
    raw_type,
    message_content,
    compress_content=None,
    group_prefix_strip=False,
) -> str:
    t = low_type(raw_type)
    text = decode_blob(message_content)
    if not text and compress_content not in (None, b"", ""):
        text = decode_blob(compress_content)

    if group_prefix_strip:
        _, text = strip_group_prefix(text)

    if t == 1:
        if text:
            if "<appmsg" in text or text.lstrip().startswith("<msg"):
                parsed = parse_app_message(text)
                if parsed and parsed != "[文件/链接/卡片]":
                    return parsed
            return clean_text(text)
        return "[文本]"
    if t == 49:
        return parse_app_message(text)
    if t == 3:
        return "[图片]"
    if t == 34:
        return "[语音]"
    if t == 43:
        return "[视频]"
    if t == 47:
        return "[动画表情]"
    if t == 48:
        return "[位置]"
    if t == 10000:
        return parse_system_message(text)
    return clean_text(text) if text else f"[消息 type={raw_type}]"


def find_contact(db: WeChatDB, keyword: str):
    results = db.search_contact(keyword)
    if not results:
        raise ValueError(f"没有找到联系人或群聊：{keyword}")

    exact = [
        x for x in results
        if x.get("remark") == keyword or x.get("nick_name") == keyword
    ]
    return exact[0] if exact else results[0]


def table_columns(conn, table: str) -> set[str]:
    return {
        r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def load_rows(db: WeChatDB, username: str):
    """跨全部 message_*.db 读取，保留来源库，避免只命中第一个分片。"""
    md5hex = hashlib.md5(username.encode("utf-8")).hexdigest()
    table = "Msg_" + md5hex
    rows = []

    for rel in db._message_dbs():
        conn = db._open(rel)
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                continue

            cols = table_columns(conn, table)
            wanted = [
                "local_id", "local_type", "server_id", "real_sender_id",
                "create_time", "message_content", "source", "compress_content",
                "packed_info_data", "sort_seq",
            ]
            select_cols = [c for c in wanted if c in cols]
            cur = conn.execute(
                "SELECT " + ", ".join(select_cols) + f" FROM {table}"
            )
            names = [d[0] for d in cur.description]
            for raw in cur.fetchall():
                item = dict(zip(names, raw))
                for c in wanted:
                    item.setdefault(c, None)
                item["_db_rel"] = rel
                rows.append(item)
        finally:
            conn.close()

    rows.sort(
        key=lambda r: (
            (r.get("sort_seq") or 0),
            (r.get("local_id") or 0),
        )
    )
    return rows


def fmt_time(ts) -> str:
    try:
        value = int(ts)
        if value > 10_000_000_000:
            value //= 1000
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts or "")


def resolve_sender(
    db: WeChatDB,
    row,
    is_group,
    target_name,
    sender_index,
    nicks,
    self_nick,
):
    sid = row.get("real_sender_id")
    if sid in (2, "2"):
        return "我", False

    # 群聊：优先从消息正文前缀取真实成员 wxid。
    if is_group:
        raw_text = decode_blob(row.get("message_content"))
        prefix_wxid, _ = strip_group_prefix(raw_text)
        if prefix_wxid:
            return nicks.get(prefix_wxid, prefix_wxid), True

    try:
        resolved = db._resolve_sender(sid, sender_index, nicks, self_nick)
    except Exception:
        resolved = ""

    if resolved == self_nick:
        return "我", False

    if is_group:
        if resolved and resolved != str(sid):
            return resolved, False
        return (
            f"成员#{sid}" if sid not in (None, "") else "未知成员"
        ), False

    if not resolved or resolved == str(sid):
        return target_name, False
    return resolved, False



def _extract_media_md5(row: dict) -> str:
    """旧式兜底：从消息自身字段里找 32 位十六进制串。

    注意：微信 4.x 图片文件名使用的 fileHash 不一定等于消息 XML 里的 md5，
    所以图片定位会优先查询 message_resource.db，这里只做 fallback。
    """
    for value in (row.get("packed_info_data"), row.get("message_content")):
        if isinstance(value, (bytes, bytearray)):
            m = re.search(rb"([0-9a-fA-F]{32})", bytes(value))
            if m:
                return m.group(1).decode("ascii").lower()
        elif isinstance(value, str):
            m = re.search(r"([0-9a-fA-F]{32})", value)
            if m:
                return m.group(1).lower()
    return ""


def _find_db_rel(db: WeChatDB, basename: str):
    target = basename.casefold()
    for item in getattr(db, "_db_files", []):
        if len(item) < 2:
            continue
        rel, path = item[0], item[1]
        if Path(path).name.casefold() == target:
            return rel
    return None


def _extract_resource_hash(blob) -> str:
    """从 MessageResourceInfo.packed_info 的 protobuf blob 中提取图片 fileHash。"""
    if blob is None:
        return ""
    if isinstance(blob, str):
        data = blob.encode("utf-8", "ignore")
    elif isinstance(blob, (bytes, bytearray, memoryview)):
        data = bytes(blob)
    else:
        return ""

    # 常见 protobuf: 12 22 0a 20 + 32 ASCII hex
    marker = b"\x12\x22\x0a\x20"
    pos = data.find(marker)
    if pos >= 0 and pos + 4 + 32 <= len(data):
        cand = data[pos + 4: pos + 4 + 32]
        if re.fullmatch(rb"[0-9a-fA-F]{32}", cand):
            return cand.decode("ascii").lower()

    # 兜底：任意独立的 32 位 hex 串。
    m = re.search(rb"(?<![0-9a-fA-F])([0-9a-fA-F]{32})(?![0-9a-fA-F])", data)
    if m:
        return m.group(1).decode("ascii").lower()
    return ""


def _resource_image_hash(db: WeChatDB, username: str, local_id) -> str:
    """通过 message_resource.db 的 chat_id + message_local_id 取得真实 .dat fileHash。"""
    if local_id in (None, ""):
        return ""
    rel = _find_db_rel(db, "message_resource.db")
    if not rel:
        return ""

    conn = db._open(rel)
    try:
        row = conn.execute(
            "SELECT rowid FROM ChatName2Id WHERE user_name=? LIMIT 1",
            (username,),
        ).fetchone()
        if not row:
            return ""
        chat_id = row[0]

        info = conn.execute(
            "SELECT packed_info FROM MessageResourceInfo "
            "WHERE chat_id=? AND message_local_id=? LIMIT 1",
            (chat_id, local_id),
        ).fetchone()
        if not info:
            return ""
        return _extract_resource_hash(info[0])
    except Exception:
        return ""
    finally:
        conn.close()


def _index_image_files(db: WeChatDB, username: str) -> dict[str, Path]:
    chat_md5 = hashlib.md5(username.encode("utf-8")).hexdigest()
    base = Path(db.account_dir) / "msg" / "attach" / chat_md5
    if not base.exists():
        return {}

    out = {}
    try:
        for p in base.rglob("*.dat"):
            out.setdefault(p.name.lower(), p)
    except OSError:
        pass
    return out


def _normalize_timestamp(ts) -> int:
    try:
        value = int(ts)
        if value > 10_000_000_000:
            value //= 1000
        return value
    except Exception:
        return 0


def _find_plain_thumbnail(
    db: WeChatDB,
    username: str,
    local_id,
    create_time,
) -> Path | None:
    """查找微信已生成的明文聊天缩略图，不需要图片 AES 密钥。"""
    ts = _normalize_timestamp(create_time)
    if not ts or local_id in (None, ""):
        return None

    chat_md5 = hashlib.md5(username.encode("utf-8")).hexdigest()
    month = datetime.fromtimestamp(ts).strftime("%Y-%m")
    thumb_dir = (
        Path(db.account_dir)
        / "cache"
        / month
        / "Message"
        / chat_md5
        / "Thumb"
    )
    if not thumb_dir.exists():
        return None

    exact = thumb_dir / f"{local_id}_{ts}_thumb.jpg"
    if exact.exists():
        return exact

    # create_time 在部分表中精度/值会略有差异，按 local_id 兜底。
    prefix = f"{local_id}_"
    try:
        hits = [
            p for p in thumb_dir.iterdir()
            if p.is_file() and p.name.startswith(prefix)
        ]
    except OSError:
        return None
    if not hits:
        return None
    try:
        return max(hits, key=lambda p: p.stat().st_mtime)
    except OSError:
        return hits[0]


def _filename_key(name: str) -> str:
    return unicodedata.normalize("NFC", name or "").strip().casefold()


def _filename_loose_key(name: str) -> str:
    """忽略 Windows 重名下载产生的 (1)/(2) 后缀后匹配。"""
    name = unicodedata.normalize("NFC", name or "").strip()
    p = Path(name)
    stem = re.sub(r"\s*[\(（]\d+[\)）]\s*$", "", p.stem)
    return (stem + p.suffix).casefold()


def _index_local_files(db: WeChatDB) -> dict:
    """索引微信可能使用的文件缓存目录；同时建立严格/宽松文件名索引。"""
    roots = [
        Path(db.account_dir) / "msg" / "file",
        Path(db.account_dir) / "FileStorage" / "File",
        Path(db.account_dir) / "file",
    ]
    # 老版本/迁移目录可能还保留 MsgAttach。仅在目录存在时索引。
    msg_attach = Path(db.account_dir) / "FileStorage" / "MsgAttach"
    if msg_attach.exists():
        roots.append(msg_attach)

    exact: dict[str, list[Path]] = {}
    loose: dict[str, list[Path]] = {}
    seen = set()

    for base in roots:
        if not base.exists():
            continue
        try:
            iterator = base.rglob("*")
            for p in iterator:
                if not p.is_file():
                    continue
                try:
                    rp = str(p.resolve())
                except OSError:
                    rp = str(p)
                if rp in seen:
                    continue
                seen.add(rp)
                exact.setdefault(_filename_key(p.name), []).append(p)
                loose.setdefault(_filename_loose_key(p.name), []).append(p)
        except OSError:
            continue

    return {
        "exact": exact,
        "loose": loose,
        "count": len(seen),
        "roots": [str(p) for p in roots if p.exists()],
    }


def _pick_file_candidate(candidates: list[Path], create_time) -> Path | None:
    if not candidates:
        return None
    month = ""
    try:
        value = _normalize_timestamp(create_time)
        if value:
            month = datetime.fromtimestamp(value).strftime("%Y-%m")
    except Exception:
        pass

    if month:
        month_hits = [p for p in candidates if month in p.parts]
        if month_hits:
            candidates = month_hits

    try:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    except OSError:
        return candidates[0]


def _relative_media_path(chat_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(chat_dir.resolve()).as_posix()


def _markdown_href(rel_path: str) -> str:
    return quote(rel_path.replace("\\", "/"), safe="/._-~")




def _ensure_cfg_dword(db: WeChatDB):
    """keys.json 命中时上游不会再提取 cfgDword；媒体导出时主动补取一次。"""
    current = getattr(db, "cfg_dword", None)
    if current:
        return current, None
    try:
        auto = db.extract_master_key()
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not auto:
        return None, "未能从当前微信进程提取 cfgDword"
    master, cfg_dword, _wxid = auto
    if master:
        db.master_key = master
    if cfg_dword:
        db.cfg_dword = cfg_dword
        return cfg_dword, None
    return None, "提取结果中没有 cfgDword"


def _detect_image_keys_fast(md: MediaDownloader):
    """尽量快速获取图片 AES/XOR 密钥，不进入上游 120 秒监控等待。"""
    try:
        templates = md._collect_templates()
        xor_key = md._get_xor_key(templates)
        if xor_key is None:
            dat = md._dbg_last_dat()
            xor_key = md._derive_xor_key(dat) if dat else 0x88

        derived = md._derive_cfg_key()
        if derived:
            return derived[0], xor_key

        aes_key = None
        image_key = getattr(md, "_image_key", None)
        if image_key and md._validate_key(image_key):
            aes_key = image_key
        if not aes_key:
            aes_key = md._load_persisted_key()
        if not aes_key:
            aes_key = md._scan_aes_key(monitor=False)
            if aes_key:
                md._persist_key(aes_key)
        if not aes_key:
            return None
        return aes_key, xor_key
    except Exception:
        return None




def _wxgf_extract_units(buf: bytes):
    starts = []
    i = 4
    n = len(buf)
    while i < n - 3:
        if buf[i:i + 4] == b"\x00\x00\x00\x01":
            starts.append((i, 4))
            i += 4
            continue
        if buf[i:i + 3] == b"\x00\x00\x01":
            starts.append((i, 3))
            i += 3
            continue
        i += 1

    units = []
    for k, (start, prefix_len) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else n
        payload = buf[start + prefix_len:end]
        if len(payload) < 2:
            continue
        if payload[0] & 0x80:
            continue
        units.append(payload)
    return units


def _wxgf_nal_type(unit: bytes) -> int:
    return (unit[0] >> 1) & 0x3F if len(unit) >= 2 else -1


def _wxgf_merge_units(units) -> bytes:
    return b"".join(b"\x00\x00\x00\x01" + u for u in units if len(u) >= 2)


def _wxgf_candidates(buf: bytes):
    units = _wxgf_extract_units(buf)
    candidates = []

    def add(name, data):
        if not data or len(data) < 100:
            return
        if any(existing == data for _, existing in candidates):
            return
        candidates.append((name, data))

    vps_starts = [i for i, u in enumerate(units) if _wxgf_nal_type(u) == 32]
    groups = []
    for gi, start in enumerate(vps_starts):
        end = vps_starts[gi + 1] if gi + 1 < len(vps_starts) else len(units)
        group_units = units[start:end]
        if not group_units:
            continue
        if not any(_wxgf_nal_type(u) in {1, 19, 20} for u in group_units):
            continue
        merged = _wxgf_merge_units(group_units)
        groups.append((gi, merged))

    groups.sort(key=lambda x: len(x[1]), reverse=True)
    for gi, data in groups:
        add(f"group_{gi}", data)

    add("scan_all_nalus", _wxgf_merge_units(units))
    add("raw_skip4", buf[4:])
    return candidates


def _subprocess_no_window():
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = 0
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def _jpeg_quality_score(path: Path):
    try:
        with Image.open(path) as im:
            im.load()
            rgb = im.convert("RGB")
            rgb.thumbnail((256, 256))
            stat = ImageStat.Stat(rgb)
            contrast = sum(stat.stddev) / 3.0
            gray = rgb.convert("L")
            hist = gray.histogram()
            total = max(1, sum(hist))
            near_white = sum(hist[250:256]) / total
            near_black = sum(hist[0:6]) / total
            uniform = max(near_white, near_black)
            blank = contrast < 2.0 and uniform > 0.985
            score = contrast + (1.0 - uniform) * 50.0
            return score, blank
    except Exception:
        return -1.0, True


def _wxgf_to_jpg_robust(data: bytes):
    if data[:4] != b"wxgf":
        return None

    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None

    best = None
    best_score = -1.0

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        for idx, (_name, candidate) in enumerate(_wxgf_candidates(data)):
            src = td_path / f"in_{idx}.hevc"
            dst = td_path / f"out_{idx}.jpg"
            try:
                src.write_bytes(candidate)
                r = subprocess.run(
                    [
                        exe, "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "hevc", "-i", str(src),
                        "-vframes", "1", "-q:v", "2",
                        "-f", "image2", str(dst),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    **_subprocess_no_window(),
                )
            except Exception:
                continue

            if r.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
                continue

            score, blank = _jpeg_quality_score(dst)
            if blank:
                continue

            try:
                jpg = dst.read_bytes()
            except OSError:
                continue

            if jpg[:3] != b"\xff\xd8\xff":
                continue

            if score > best_score:
                best_score = score
                best = jpg

    return best



def _write_image_from_row(
    db: WeChatDB,
    md: MediaDownloader,
    row: dict,
    username: str,
    image_index: dict[str, Path],
    image_dir: Path,
    image_keys,
):
    """优先导出原图；无法解密时回退微信明文缩略图。"""
    local_id = row.get("local_id")

    # 微信 4.x .dat 文件名通常不是 XML md5，优先从 message_resource.db 解析 fileHash。
    file_hash = _resource_image_hash(db, username, local_id)
    if not file_hash:
        file_hash = _extract_media_md5(row)

    dat_path = None
    variant = "original"
    if file_hash:
        # 顺序：普通图 → 高清图 → 加密缩略图
        for suffix, var in (
            (".dat", "original"),
            ("_h.dat", "high"),
            ("_t.dat", "thumbnail-dat"),
        ):
            candidate = image_index.get((file_hash + suffix).lower())
            if candidate is not None:
                dat_path = candidate
                variant = var
                break

    # 找到了 .dat 且有密钥/旧格式可解，就优先输出它。
    dat_reason = None
    if dat_path is not None:
        aes_key = image_keys[0] if image_keys else None
        xor_key = image_keys[1] if image_keys else None

        try:
            with dat_path.open("rb") as fh:
                magic = fh.read(6)
        except OSError as exc:
            magic = b""
            dat_reason = f"图片缓存读取失败：{exc}"

        if not dat_reason:
            if magic == b"\x07\x08\x56\x32\x08\x07" and not image_keys:
                dat_reason = "V2 图片缺少解密密钥"
            else:
                try:
                    data = md.decrypt_image(
                        str(dat_path),
                        aes_key=aes_key,
                        xor_key=xor_key,
                    )
                except Exception as exc:
                    dat_reason = f"图片解密失败：{type(exc).__name__}: {exc}"
                else:
                    if data[:3] == b"\xff\xd8\xff":
                        ext = ".jpg"
                    elif data[:4] == b"\x89PNG":
                        ext = ".png"
                    elif data[:3] == b"GIF":
                        ext = ".gif"
                    elif data[:4] == b"RIFF":
                        ext = ".webp"
                    elif data[:4] == b"wxgf":
                        # 微信 4.x 的 wxgf/HEVC 图片直接取“第一帧”有时会得到纯白图。
                        # 优先使用微信自己已经生成的明文聊天缩略图，稳定性更高，
                        # 且足够用于 Markdown 直接预览；只有没有缩略图时才尝试 ffmpeg。
                        plain_thumb = _find_plain_thumbnail(
                            db,
                            username,
                            local_id,
                            row.get("create_time"),
                        )
                        if plain_thumb is not None:
                            image_dir.mkdir(parents=True, exist_ok=True)
                            seq = row.get("sort_seq") or local_id or "image"
                            lid = local_id or "0"
                            thumb_ext = plain_thumb.suffix.lower() if plain_thumb.suffix else ".jpg"
                            if thumb_ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                                thumb_ext = ".jpg"
                            out = image_dir / f"{seq}_{lid}_thumb{thumb_ext}"
                            try:
                                shutil.copy2(plain_thumb, out)
                            except OSError as exc:
                                dat_reason = f"wxgf 缩略图复制失败：{exc}"
                            else:
                                return {
                                    "kind": "image",
                                    "path": str(out),
                                    "variant": "thumbnail-cache",
                                    "previewable": True,
                                }, None
                        try:
                            jpg = _wxgf_to_jpg_robust(data)
                        except Exception:
                            jpg = None
                        if jpg is not None:
                            data = jpg
                            ext = ".jpg"
                        else:
                            ext = ".wxgf"
                    else:
                        ext = ".img"

                    image_dir.mkdir(parents=True, exist_ok=True)
                    seq = row.get("sort_seq") or local_id or "image"
                    lid = local_id or "0"
                    suffix = (
                        "_thumb"
                        if variant.startswith("thumbnail")
                        else "_high" if variant == "high" else ""
                    )
                    out = image_dir / f"{seq}_{lid}{suffix}{ext}"
                    try:
                        out.write_bytes(data)
                    except OSError as exc:
                        dat_reason = f"图片写入失败：{exc}"
                    else:
                        return {
                            "kind": "image",
                            "path": str(out),
                            "variant": variant,
                            "previewable": ext.lower()
                            in {".jpg", ".jpeg", ".png", ".gif", ".webp"},
                        }, None

    # 关键兜底：微信聊天缩略图缓存本身是明文 JPEG，不需要图片 AES 密钥。
    thumb = _find_plain_thumbnail(
        db,
        username,
        local_id,
        row.get("create_time"),
    )
    if thumb is not None:
        image_dir.mkdir(parents=True, exist_ok=True)
        seq = row.get("sort_seq") or local_id or "image"
        lid = local_id or "0"
        ext = thumb.suffix.lower() if thumb.suffix else ".jpg"
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            ext = ".jpg"
        out = image_dir / f"{seq}_{lid}_thumb{ext}"
        try:
            shutil.copy2(thumb, out)
        except OSError as exc:
            return None, f"缩略图复制失败：{exc}"
        return {
            "kind": "image",
            "path": str(out),
            "variant": "thumbnail-cache",
            "previewable": True,
        }, None

    if not file_hash:
        return None, "未从 message_resource/消息字段解析到图片 fileHash，且无明文缩略图"
    if dat_path is None:
        return None, "已解析图片 fileHash，但本机 attach 目录没有对应 .dat，且无明文缩略图"
    return None, dat_reason or "图片缓存存在但无法导出"



def _file_name_candidates(
    md: MediaDownloader,
    row: dict,
    parsed_content: str,
) -> list[str]:
    """同时使用 appmsg 标题和 message_resource 文件名，避免单一路径误判。"""
    names = []

    if parsed_content.startswith("[文件]"):
        title = parsed_content[len("[文件]"):].strip()
        if title:
            names.append(safe_file_name(title, "file"))

    media_row = {"server_id": row.get("server_id")}
    try:
        resource_name = md._file_name(media_row)
    except Exception:
        resource_name = None
    if resource_name:
        resource_name = safe_file_name(resource_name, "file")
        if resource_name not in names:
            names.append(resource_name)

    return names


def _copy_file_from_row(
    md: MediaDownloader,
    row: dict,
    parsed_content: str,
    file_index: dict,
    file_dir: Path,
):
    names = _file_name_candidates(md, row, parsed_content)
    if not names:
        return None, "未从文件消息中解析到文件名"

    exact = file_index.get("exact", {})
    loose = file_index.get("loose", {})
    src = None
    matched_name = None

    # 先严格匹配；再兼容 Windows 下载重名时自动变成 xxx(1).ext。
    for name in names:
        candidates = exact.get(_filename_key(name), [])
        src = _pick_file_candidate(candidates, row.get("create_time"))
        if src is not None:
            matched_name = name
            break

    if src is None:
        for name in names:
            candidates = loose.get(_filename_loose_key(name), [])
            src = _pick_file_candidate(candidates, row.get("create_time"))
            if src is not None:
                matched_name = src.name
                break

    if src is None:
        shown = " / ".join(names)
        roots = file_index.get("roots", [])
        if not roots:
            return None, f"没有找到微信本地文件缓存目录；消息文件名：{shown}"
        return None, f"缓存目录中未匹配到文件：{shown}"

    file_dir.mkdir(parents=True, exist_ok=True)
    seq = row.get("sort_seq") or row.get("local_id") or "file"
    lid = row.get("local_id") or "0"
    out_name = safe_file_name(src.name or matched_name or names[0], "file")
    out = file_dir / f"{seq}_{lid}_{out_name}"

    try:
        if out.exists():
            out = file_dir / f"{seq}_{lid}_{src.stat().st_size}_{out_name}"
        shutil.copy2(src, out)
    except OSError as exc:
        return None, f"文件复制失败：{exc}"

    return {
        "kind": "file",
        "path": str(out),
        "name": src.name or matched_name or names[0],
        "previewable": False,
    }, None


def _media_label(media: dict) -> str:
    return {
        "image": "图片",
        "file": "文件",
        "voice": "语音",
        "video": "视频",
    }.get(media.get("kind"), "附件")


def _voice_transcript(row: dict) -> str:
    """读取微信本机已存在的语音转文字。

    微信 4.x 不同小版本/消息形态可能把转写放在 message_content、
    source、compress_content 或 packed_info_data 中，因此这里统一扫描。
    """
    values = (
        row.get("message_content"),
        row.get("source"),
        row.get("compress_content"),
        row.get("packed_info_data"),
    )

    for value in values:
        if value in (None, b"", ""):
            continue

        candidates = []
        decoded = decode_blob(value)
        if decoded:
            candidates.append(decoded)
            unescaped = html.unescape(decoded)
            if unescaped != decoded:
                candidates.append(unescaped)

        if isinstance(value, (bytes, bytearray, memoryview)):
            raw_text = bytes(value).decode("utf-8", errors="ignore").replace("\x00", "")
            if raw_text and raw_text not in candidates:
                candidates.append(raw_text)

        for text_value in candidates:
            if not text_value:
                continue

            # 标准 XML: <voicetrans transtext="..." ... />
            if "voicetrans" in text_value.lower():
                root = xml_root(text_value)
                if root is not None:
                    node = root.find(".//voicetrans")
                    if node is not None:
                        transcript = clean_text(
                            node.get("transtext")
                            or node.get("text")
                            or node.text
                            or ""
                        )
                        if transcript:
                            return transcript

            patterns = (
                r'transtext\s*=\s*["\'](.*?)["\']',
                r'"transtext"\s*:\s*"((?:\\.|[^"])*)"',
                r"'transtext'\s*:\s*'((?:\\.|[^'])*)'",
                r'voice[_-]?trans(?:cript|text)\s*[:=]\s*["\'](.*?)["\']',
            )
            for pattern in patterns:
                hit = re.search(pattern, text_value, re.I | re.S)
                if not hit:
                    continue
                transcript = hit.group(1)
                try:
                    transcript = bytes(transcript, "utf-8").decode("unicode_escape")
                except Exception:
                    pass
                transcript = clean_text(transcript)
                if transcript:
                    return transcript

    return ""


def _voice_data_from_row(db: WeChatDB, username: str, row: dict):
    server_id = row.get("server_id")
    local_id = row.get("local_id")
    create_time = _normalize_timestamp(row.get("create_time"))

    for item in getattr(db, "_db_files", []):
        if len(item) < 2:
            continue
        rel, path = item[0], item[1]
        if not Path(path).name.lower().startswith("media_"):
            continue
        conn = db._open(rel)
        try:
            has_name = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='Name2Id'"
            ).fetchone()
            has_voice = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='VoiceInfo'"
            ).fetchone()
            if not has_name or not has_voice:
                continue
            cid = conn.execute(
                "SELECT rowid FROM Name2Id WHERE user_name=? LIMIT 1", (username,)
            ).fetchone()
            if not cid:
                continue
            chat_id = cid[0]
            cols = table_columns(conn, "VoiceInfo")
            attempts = []
            if server_id not in (None, "") and "svr_id" in cols:
                attempts.append(("chat_name_id=? AND svr_id=?", [chat_id, server_id]))
            if local_id not in (None, "") and "local_id" in cols:
                attempts.append(("chat_name_id=? AND local_id=?", [chat_id, local_id]))
            if create_time and "create_time" in cols:
                attempts.append(("chat_name_id=? AND create_time=?", [chat_id, create_time]))
            for where, params in attempts:
                found = conn.execute(
                    f"SELECT voice_data FROM VoiceInfo WHERE {where} "
                    "AND voice_data IS NOT NULL LIMIT 1",
                    params,
                ).fetchone()
                if found and found[0]:
                    return bytes(found[0]), None
        except Exception:
            continue
        finally:
            conn.close()
    return None, "media_*.db 中没有匹配到 VoiceInfo.voice_data"


def _runtime_resource(*parts) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent
    return base.joinpath(*parts)


def _find_rust_silk() -> Path | None:
    candidates = [
        _runtime_resource("tools", "rust-silk.exe"),
        Path(__file__).resolve().parent / "tools" / "rust-silk.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    found = shutil.which("rust-silk")
    return Path(found) if found else None


def _decode_silk_to_wav(silk_path: Path, wav_path: Path):
    exe = _find_rust_silk()
    if exe is None:
        return False, "未找到 rust-silk 解码器；已保留原始 SILK"
    try:
        result = subprocess.run(
            [
                str(exe), "decode",
                "-i", str(silk_path),
                "-o", str(wav_path),
                "--tolerant", "skip",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            **_subprocess_no_window(),
        )
    except Exception as exc:
        return False, f"rust-silk 启动失败：{type(exc).__name__}: {exc}"
    if result.returncode == 0 and wav_path.exists() and wav_path.stat().st_size > 44:
        return True, None
    err = result.stderr.decode("utf-8", "ignore").strip()
    return False, f"SILK→WAV 失败：{err[:300] or '未知错误'}"


def _write_voice_from_row(db, row, username, voice_dir: Path):
    data, reason = _voice_data_from_row(db, username, row)
    transcript = _voice_transcript(row)
    if not data:
        return None, reason, transcript

    voice_dir.mkdir(parents=True, exist_ok=True)
    seq = row.get("sort_seq") or row.get("local_id") or "voice"
    lid = row.get("local_id") or "0"
    silk_path = voice_dir / f"{seq}_{lid}.silk"
    try:
        silk_path.write_bytes(data)
    except OSError as exc:
        return None, f"写入 SILK 失败：{exc}", transcript

    wav_path = voice_dir / f"{seq}_{lid}.wav"
    decoded, decode_reason = _decode_silk_to_wav(silk_path, wav_path)

    # 对普通用户只保留可直接播放的 WAV。
    # SILK 仅在 WAV 解码失败时作为兜底保留。
    if decoded:
        try:
            silk_path.unlink(missing_ok=True)
        except OSError:
            pass

    media = {
        "kind": "voice",
        "path": str(wav_path if decoded else silk_path),
        "silk_path": None if decoded else str(silk_path),
        "format": "wav" if decoded else "silk",
        "decoded": decoded,
        "transcript": transcript,
        "voice_sha256": hashlib.sha256(data).hexdigest(),
        "previewable": False,
    }
    return media, decode_reason, transcript



SENSEVOICE_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2"
)
SENSEVOICE_MODEL_SHA256 = "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51"


def _persistent_app_data_dir() -> Path:
    """长期数据放在用户应用数据目录，不混进导出文件夹。"""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "WeChat-Chat-Export-for-LLM"
    return Path.home() / ".wechat-chat-export-for-llm"


def _persistent_sensevoice_dir() -> Path:
    """模型放在用户目录，避免 PyInstaller onefile 每次启动后丢失。"""
    return _persistent_app_data_dir() / "models" / "sensevoice"


def _persistent_asr_cache_path() -> Path:
    return _persistent_app_data_dir() / "cache" / "voice_asr_cache.json"


def _find_sensevoice_model():
    """返回本地 SenseVoice 模型与 tokens 路径。"""
    persistent = _persistent_sensevoice_dir()
    candidates = [
        (persistent / "model.int8.onnx", persistent / "tokens.txt"),
        (
            _runtime_resource("tools", "asr", "sensevoice", "model.int8.onnx"),
            _runtime_resource("tools", "asr", "sensevoice", "tokens.txt"),
        ),
        (
            Path(__file__).resolve().parent / "tools" / "asr" / "sensevoice" / "model.int8.onnx",
            Path(__file__).resolve().parent / "tools" / "asr" / "sensevoice" / "tokens.txt",
        ),
    ]
    for model, tokens in candidates:
        if model.exists() and tokens.exists():
            return model, tokens
    return None, None


def _local_asr_runtime_status():
    try:
        import sherpa_onnx  # noqa: F401
        import soundfile  # noqa: F401
    except Exception as exc:
        return False, f"本地语音识别运行库不可用：{type(exc).__name__}: {exc}"
    return True, ""


def local_asr_status():
    """供 GUI/CLI 在开始导出前检查本地语音识别。"""
    ok, reason = _local_asr_runtime_status()
    if not ok:
        return False, reason
    model, tokens = _find_sensevoice_model()
    if not model or not tokens:
        return False, "未安装 SenseVoice 本地语音识别模型"
    return True, ""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def install_local_asr_model(progress=None):
    """显式下载并安装 SenseVoice Small Int8 模型。不会上传聊天内容。"""
    def log(message):
        if progress:
            progress(message)

    ok, reason = _local_asr_runtime_status()
    if not ok:
        raise RuntimeError(reason)

    existing_model, existing_tokens = _find_sensevoice_model()
    if existing_model and existing_tokens:
        if _sha256_file(existing_model).lower() == SENSEVOICE_MODEL_SHA256:
            log("SenseVoice 模型已经安装，无需重复下载。")
            return str(existing_model)

    target_dir = _persistent_sensevoice_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="wechat-chat-export-asr-") as td:
        td = Path(td)
        archive = td / "sensevoice.tar.bz2"
        log("正在下载 SenseVoice Small Int8 模型（约 230 MB）…")

        request = urllib.request.Request(
            SENSEVOICE_MODEL_URL,
            headers={"User-Agent": "WeChat-Chat-Export-for-LLM/1.3.0"},
        )
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as f:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            last_percent = -10
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    percent = int(downloaded * 100 / total)
                    if percent >= last_percent + 10:
                        last_percent = (percent // 10) * 10
                        log(f"模型下载：{min(percent, 100)}%")

        log("正在解压模型…")
        model_tmp = td / "model.int8.onnx"
        tokens_tmp = td / "tokens.txt"
        license_tmp = td / "MODEL_LICENSE"
        readme_tmp = td / "MODEL_README.md"

        wanted = {
            "model.int8.onnx": model_tmp,
            "tokens.txt": tokens_tmp,
            "LICENSE": license_tmp,
            "README.md": readme_tmp,
        }
        found = set()
        with tarfile.open(archive, "r:bz2") as tf:
            for member in tf.getmembers():
                name = Path(member.name).name
                if name not in wanted or name in found or not member.isfile():
                    continue
                source = tf.extractfile(member)
                if source is None:
                    continue
                with source, wanted[name].open("wb") as dst:
                    shutil.copyfileobj(source, dst)
                found.add(name)

        if not model_tmp.exists() or not tokens_tmp.exists():
            raise RuntimeError("下载的模型包缺少 model.int8.onnx 或 tokens.txt")

        actual = _sha256_file(model_tmp).lower()
        if actual != SENSEVOICE_MODEL_SHA256:
            raise RuntimeError(
                "SenseVoice 模型校验失败。"
                f"\n预期 SHA-256：{SENSEVOICE_MODEL_SHA256}"
                f"\n实际 SHA-256：{actual}"
            )

        log("模型校验通过，正在安装…")
        for src_file, dest_name in (
            (model_tmp, "model.int8.onnx"),
            (tokens_tmp, "tokens.txt"),
            (license_tmp, "MODEL_LICENSE"),
            (readme_tmp, "MODEL_README.md"),
        ):
            if not src_file.exists():
                continue
            tmp_dest = target_dir / (dest_name + ".tmp")
            shutil.copy2(src_file, tmp_dest)
            os.replace(tmp_dest, target_dir / dest_name)

    log("SenseVoice 本地语音识别模型安装完成。")
    return str(target_dir / "model.int8.onnx")


def _create_local_asr_recognizer():
    ok, reason = local_asr_status()
    if not ok:
        raise RuntimeError(reason)

    import sherpa_onnx

    model, tokens = _find_sensevoice_model()
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model),
        tokens=str(tokens),
        num_threads=4,
        language="auto",
        use_itn=True,
        debug=False,
        provider="cpu",
    )


def _asr_result_text(result) -> str:
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return clean_text(text)

    if isinstance(result, str):
        raw = result.strip()
    else:
        raw = str(result).strip()

    if not raw:
        return ""

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and isinstance(obj.get("text"), str):
            return clean_text(obj["text"])
    except Exception:
        pass

    return clean_text(raw)


def _transcribe_wav_local(recognizer, wav_path: Path):
    try:
        import soundfile as sf

        audio, sample_rate = sf.read(
            str(wav_path),
            dtype="float32",
            always_2d=True,
        )
        if len(audio) == 0:
            return "", "WAV 没有音频采样"

        # 微信语音通常是单声道；若遇到多声道则平均为单声道。
        if audio.shape[1] == 1:
            samples = audio[:, 0]
        else:
            samples = audio.mean(axis=1)

        stream = recognizer.create_stream()
        stream.accept_waveform(int(sample_rate), samples)
        recognizer.decode_stream(stream)
        text = _asr_result_text(stream.result)
        if not text:
            return "", "本地语音识别未返回文字"
        return text, None
    except Exception as exc:
        return "", f"本地语音识别失败：{type(exc).__name__}: {exc}"


def _read_asr_cache_file(path: Path) -> dict:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {
                    str(k): str(v)
                    for k, v in data.items()
                    if isinstance(k, str) and isinstance(v, str) and v.strip()
                }
    except Exception:
        pass
    return {}


def _load_asr_cache(out_root: Path):
    """读取长期 ASR 缓存，并兼容迁移 v1.3.0 发布前测试版的旧缓存位置。"""
    path = _persistent_asr_cache_path()
    cache = _read_asr_cache_file(path)

    legacy_path = out_root / ".voice_asr_cache.json"
    legacy_cache = _read_asr_cache_file(legacy_path)
    if legacy_cache:
        changed = False
        for key, value in legacy_cache.items():
            if key not in cache:
                cache[key] = value
                changed = True

        if changed or not path.exists():
            _save_asr_cache(path, cache)

        # 成功写入新位置后再移除旧缓存，让 exports 保持干净。
        try:
            if path.exists():
                legacy_path.unlink(missing_ok=True)
        except OSError:
            pass

    return path, cache


def _save_asr_cache(path: Path, cache: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        # 缓存失败不能影响聊天导出本身。
        pass


def _extract_video_id(row: dict) -> str:
    for value in (row.get("packed_info_data"), row.get("message_content")):
        if isinstance(value, (bytes, bytearray, memoryview)):
            m = re.search(rb"([0-9a-fA-F]{32})", bytes(value))
            if m:
                return m.group(1).decode("ascii").lower()
        elif isinstance(value, str):
            m = re.search(r"([0-9a-fA-F]{32})", value)
            if m:
                return m.group(1).lower()
    return ""


def _index_video_files(db: WeChatDB):
    account = Path(db.account_dir)
    roots = [account / "msg" / "video", account / "video", account / "FileStorage" / "Video"]
    index = {}
    count = 0
    for root in roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob("*.mp4"):
                if not p.is_file():
                    continue
                count += 1
                index.setdefault(p.stem.casefold(), []).append(p)
        except OSError:
            continue
    return {"by_stem": index, "count": count}


def _write_video_from_row(row, video_index, video_dir: Path):
    vid = _extract_video_id(row)
    candidates = video_index.get("by_stem", {}).get(vid.casefold(), []) if vid else []
    if not candidates:
        return None, (f"本机没有找到视频缓存：{vid}" if vid else "没有从消息中解析到视频标识")
    try:
        src = max(candidates, key=lambda p: (p.stat().st_size, p.stat().st_mtime))
    except OSError:
        src = candidates[0]
    video_dir.mkdir(parents=True, exist_ok=True)
    seq = row.get("sort_seq") or row.get("local_id") or "video"
    lid = row.get("local_id") or "0"
    out = video_dir / f"{seq}_{lid}.mp4"
    try:
        shutil.copy2(src, out)
    except OSError as exc:
        return None, f"复制视频失败：{exc}"
    return {
        "kind": "video",
        "path": str(out),
        "format": "mp4",
        "previewable": False,
    }, None


def _relativize_media(chat_dir: Path, media: dict):
    for key in ("path", "silk_path"):
        value = media.get(key)
        if not value:
            continue
        try:
            media[key] = _relative_media_path(chat_dir, Path(value))
        except Exception:
            pass
    media["available"] = True
    return media


def _write_txt(parsed: list[dict], path: Path, is_group: bool, target_name: str):
    with path.open("w", encoding="utf-8-sig", newline="\n") as f:
        f.write(f"WeChat Chat Export for LLM v{APP_VERSION}\n")
        f.write(f"会话类型：{'群聊' if is_group else '私聊'}\n")
        f.write(f"会话名称：{target_name}\n")
        f.write(f"消息总数：{len(parsed)}\n")
        f.write("=" * 70 + "\n\n")
        last_date = None
        for m in parsed:
            date = m["time"][:10] if len(m["time"]) >= 10 else ""
            if date and date != last_date:
                if last_date is not None:
                    f.write("\n")
                f.write(f"========== {date} ==========\n\n")
                last_date = date
            f.write(f"{m['time']} | {m['sender']}：{m['content'] or '[' + m['type'] + ']'}\n")
            media = m.get("media")
            if media and media.get("available") and media.get("path"):
                f.write(f"    ↳ {_media_label(media)}：{media['path']}\n")
            transcript = m.get("transcript") or (media or {}).get("transcript")
            if transcript:
                source = m.get("transcript_source") or (media or {}).get("transcript_source")
                label = "转文字（本地识别）" if source == "local_asr" else "转文字"
                f.write(f"    ↳ {label}：{transcript}\n")


def _md_message_content(content: str) -> str:
    return (content or "").replace("\n", "  \n")


def _write_markdown(parsed: list[dict], path: Path, is_group: bool, target_name: str):
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"# {target_name}\n\n")
        f.write(f"- 导出器：WeChat Chat Export for LLM v{APP_VERSION}\n")
        f.write(f"- 会话类型：{'群聊' if is_group else '私聊'}\n")
        f.write(f"- 消息总数：{len(parsed)}\n\n")
        last_date = None
        for m in parsed:
            date = m["time"][:10] if len(m["time"]) >= 10 else ""
            time_only = m["time"][11:19] if len(m["time"]) >= 19 else m["time"]
            if date and date != last_date:
                f.write(f"\n## {date}\n\n")
                last_date = date
            content = _md_message_content(m["content"] or f"[{m['type']}]")
            f.write(f"**{time_only} | {m['sender']}：** {content}\n\n")
            media = m.get("media")
            if media and media.get("available") and media.get("path"):
                href = _markdown_href(media["path"])
                kind = media.get("kind")
                if kind == "image":
                    if media.get("previewable"):
                        alt = "图片"
                        if str(media.get("variant") or "").startswith("thumbnail"):
                            alt = "图片（缩略图）"
                        safe_alt = html.escape(alt, quote=True)
                        f.write(f'<img src="{href}" alt="{safe_alt}" width="640">\n\n')
                    else:
                        f.write(f"[打开图片文件]({href})\n\n")
                elif kind == "file":
                    label = (media.get("name") or Path(media["path"]).name).replace("[", "\\[").replace("]", "\\]")
                    f.write(f"[文件：{label}]({href})\n\n")
                elif kind == "voice":
                    label = "播放语音（WAV）" if media.get("decoded") else "打开语音文件（SILK）"
                    f.write(f"[{label}]({href})\n\n")
                elif kind == "video":
                    f.write(f"[播放视频]({href})\n\n")
            transcript = m.get("transcript") or (media or {}).get("transcript")
            if transcript:
                source = m.get("transcript_source") or (media or {}).get("transcript_source")
                label = "语音转文字（本地识别）" if source == "local_asr" else "语音转文字"
                f.write(f"> {label}：{_md_message_content(transcript)}\n\n")


def export_chat(
    keyword: str,
    out_root="exports",
    progress=None,
    export_images=False,
    export_files=False,
    export_voices=False,
    export_videos=False,
    transcribe_voices=False,
):
    def log(msg):
        if progress:
            progress(msg)

    if transcribe_voices:
        export_voices = True

    log("正在连接微信本地数据库…")
    db = WeChatDB()
    target = find_contact(db, keyword)
    username = target["username"]
    target_name = target.get("remark") or target.get("nick_name") or keyword
    is_group = username.endswith("@chatroom")
    log(f"已识别：{'群聊' if is_group else '私聊'} · {target_name}")
    log("正在读取消息…")
    rows = load_rows(db, username)
    if not rows:
        raise ValueError("没有读取到该会话的消息。")

    out_root = Path(out_root)
    chat_dir = out_root / safe_folder_name(target_name)
    chat_dir.mkdir(parents=True, exist_ok=True)
    self_info = db.get_self_info()
    self_nick = self_info.get("nick_name", "我")
    sender_index = db._sender_id_index()
    nicks = db._nickname_index()
    parsed = []
    type_counts = {}

    for idx, row in enumerate(rows, 1):
        raw_type = row.get("local_type")
        t = low_type(raw_type)
        type_counts[str(t)] = type_counts.get(str(t), 0) + 1
        sender, used_group_prefix = resolve_sender(db, row, is_group, target_name, sender_index, nicks, self_nick)
        content = parse_content(raw_type, row.get("message_content"), row.get("compress_content"), group_prefix_strip=(is_group and used_group_prefix))
        transcript = _voice_transcript(row) if t == 34 else ""
        parsed.append({
            "local_id": row.get("local_id"),
            "type": TYPE_LABEL.get(t, str(t)),
            "type_code": raw_type,
            "sender": sender,
            "time": fmt_time(row.get("create_time")),
            "content": content,
            "sort_seq": row.get("sort_seq"),
            "transcript": transcript or None,
            "transcript_source": "wechat" if transcript else None,
            "media": None,
        })
        if progress and idx % 2000 == 0:
            log(f"已处理 {idx}/{len(rows)} 条消息…")

    media_stats = {
        "images_requested": 0, "images_exported": 0,
        "files_requested": 0, "files_exported": 0,
        "voices_requested": 0, "voices_exported": 0, "voices_decoded": 0,
        "voice_transcripts": 0,
        "voice_transcripts_native": 0,
        "voice_transcripts_local": 0,
        "voice_transcripts_cached": 0,
        "voice_transcripts_failed": 0,
        "videos_requested": 0, "videos_exported": 0,
    }

    if export_images or export_files or export_voices or export_videos:
        md = MediaDownloader(db)
        image_rows_exist = export_images and any(low_type(r.get("local_type")) == 3 for r in rows)
        file_rows_exist = export_files and any(
            low_type(r.get("local_type")) == 49 and parse_content(r.get("local_type"), r.get("message_content"), r.get("compress_content")).startswith("[文件]")
            for r in rows
        )
        video_rows_exist = export_videos and any(low_type(r.get("local_type")) == 43 for r in rows)
        image_index, image_keys, file_index, video_index = {}, None, {}, {}
        image_failures, file_failures, voice_failures, video_failures = Counter(), Counter(), Counter(), Counter()

        if image_rows_exist:
            log("正在定位本机图片缓存…")
            image_index = _index_image_files(db, username)
            log("正在准备图片解密配置…")
            cfg_dword, cfg_error = _ensure_cfg_dword(db)
            if cfg_dword:
                try:
                    md._cfg_dword = cfg_dword
                except Exception:
                    pass
                log("已获取图片解密配置。")
            elif cfg_error:
                log(f"图片解密配置暂未获取：{cfg_error}")
            if image_index:
                image_keys = _detect_image_keys_fast(md)
                log("图片解密密钥已就绪。" if image_keys else "未获取到图片解密密钥；将优先回退导出微信明文缩略图。")

        if file_rows_exist:
            log("正在索引本机文件缓存…")
            file_index = _index_local_files(db)
            log(f"已索引本机文件缓存：{file_index.get('count', 0)} 个文件。")

        if video_rows_exist:
            log("正在索引本机视频缓存…")
            video_index = _index_video_files(db)
            log(f"已索引本机视频缓存：{video_index.get('count', 0)} 个 MP4。")

        if export_voices and _find_rust_silk() is None:
            log("未找到 rust-silk：语音仍会导出为 SILK，但暂不能自动生成 WAV。")

        asr_recognizer = None
        asr_cache_path = None
        asr_cache = {}
        asr_cache_dirty = False
        asr_failures = Counter()
        if transcribe_voices:
            ok, reason = local_asr_status()
            if not ok:
                raise RuntimeError(
                    reason
                    + "。请先安装本地语音识别模型后重新导出。"
                )
            log("正在加载 SenseVoice 本地语音识别模型（CPU，4 线程）…")
            asr_recognizer = _create_local_asr_recognizer()
            asr_cache_path, asr_cache = _load_asr_cache(Path(out_root))
            log("本地语音识别已就绪。")

        image_dir = chat_dir / "media" / "images"
        file_dir = chat_dir / "media" / "files"
        voice_dir = chat_dir / "media" / "voices"
        video_dir = chat_dir / "media" / "videos"

        for idx, (row, msg) in enumerate(zip(rows, parsed), 1):
            t = low_type(row.get("local_type"))
            if export_images and t == 3:
                media_stats["images_requested"] += 1
                media, reason = _write_image_from_row(db, md, row, username, image_index, image_dir, image_keys)
                if media:
                    msg["media"] = _relativize_media(chat_dir, media)
                    media_stats["images_exported"] += 1
                else:
                    reason = reason or "未知原因"; image_failures[reason] += 1
                    msg["media"] = {"kind": "image", "available": False, "path": None, "reason": reason}

            elif export_files and t == 49 and msg["content"].startswith("[文件]"):
                media_stats["files_requested"] += 1
                media, reason = _copy_file_from_row(md, row, msg["content"], file_index, file_dir)
                if media:
                    msg["media"] = _relativize_media(chat_dir, media)
                    media_stats["files_exported"] += 1
                else:
                    reason = reason or "未知原因"; file_failures[reason] += 1
                    msg["media"] = {"kind": "file", "available": False, "path": None, "reason": reason}

            elif export_voices and t == 34:
                media_stats["voices_requested"] += 1
                media, reason, transcript = _write_voice_from_row(db, row, username, voice_dir)

                if transcript:
                    msg["transcript"] = transcript
                    msg["transcript_source"] = "wechat"
                    media_stats["voice_transcripts"] += 1
                    media_stats["voice_transcripts_native"] += 1

                if media:
                    media_stats["voices_exported"] += 1
                    if media.get("decoded"):
                        media_stats["voices_decoded"] += 1
                    elif reason:
                        voice_failures[reason] += 1

                    # 用户明确勾选后才运行本地 ASR。
                    if transcribe_voices and not msg.get("transcript"):
                        if media.get("decoded") and str(media.get("path") or "").lower().endswith(".wav"):
                            cache_key = media.get("voice_sha256") or ""
                            cached = asr_cache.get(cache_key) if cache_key else None
                            if cached:
                                msg["transcript"] = cached
                                msg["transcript_source"] = "local_asr"
                                media["transcript"] = cached
                                media["transcript_source"] = "local_asr"
                                media_stats["voice_transcripts"] += 1
                                media_stats["voice_transcripts_local"] += 1
                                media_stats["voice_transcripts_cached"] += 1
                            else:
                                asr_text, asr_reason = _transcribe_wav_local(
                                    asr_recognizer,
                                    Path(media["path"]),
                                )
                                if asr_text:
                                    msg["transcript"] = asr_text
                                    msg["transcript_source"] = "local_asr"
                                    media["transcript"] = asr_text
                                    media["transcript_source"] = "local_asr"
                                    media_stats["voice_transcripts"] += 1
                                    media_stats["voice_transcripts_local"] += 1
                                    if cache_key:
                                        asr_cache[cache_key] = asr_text
                                        asr_cache_dirty = True
                                else:
                                    media_stats["voice_transcripts_failed"] += 1
                                    asr_failures[asr_reason or "未知识别错误"] += 1
                        else:
                            media_stats["voice_transcripts_failed"] += 1
                            asr_failures["语音未成功转换为 WAV，无法进行本地识别"] += 1

                    msg["media"] = _relativize_media(chat_dir, media)
                else:
                    reason = reason or "未知原因"
                    voice_failures[reason] += 1
                    if transcribe_voices and not msg.get("transcript"):
                        media_stats["voice_transcripts_failed"] += 1
                        asr_failures["语音文件未成功导出"] += 1
                    msg["media"] = {
                        "kind": "voice",
                        "available": False,
                        "path": None,
                        "reason": reason,
                        "transcript": transcript,
                    }

            elif export_videos and t == 43:
                media_stats["videos_requested"] += 1
                media, reason = _write_video_from_row(row, video_index, video_dir)
                if media:
                    msg["media"] = _relativize_media(chat_dir, media)
                    media_stats["videos_exported"] += 1
                else:
                    reason = reason or "未知原因"; video_failures[reason] += 1
                    msg["media"] = {"kind": "video", "available": False, "path": None, "reason": reason}

            if progress and idx % 200 == 0:
                log(
                    f"附件处理进度：{idx}/{len(rows)}，"
                    f"图片 {media_stats['images_exported']}/{media_stats['images_requested']}，"
                    f"文件 {media_stats['files_exported']}/{media_stats['files_requested']}，"
                    f"语音 {media_stats['voices_exported']}/{media_stats['voices_requested']}，"
                    f"视频 {media_stats['videos_exported']}/{media_stats['videos_requested']}"
                )

    if transcribe_voices and 'asr_cache_dirty' in locals() and asr_cache_dirty and asr_cache_path:
        _save_asr_cache(asr_cache_path, asr_cache)

    txt_path = chat_dir / "chat_full_for_llm.txt"
    md_path = chat_dir / "chat_full_for_llm.md"
    json_path = chat_dir / "chat_full_parsed.json"
    _write_txt(parsed, txt_path, is_group, target_name)
    _write_markdown(parsed, md_path, is_group, target_name)
    with json_path.open("w", encoding="utf-8-sig") as f:
        json.dump({
            "exporter_version": APP_VERSION,
            "chat_type": "group" if is_group else "private",
            "chat_name": target_name,
            "message_count": len(parsed),
            "type_counts": type_counts,
            "media_stats": media_stats,
            "messages": parsed,
        }, f, ensure_ascii=False, indent=2)

    log(f"完成：{len(parsed)} 条消息")
    summaries = [
        (export_images, "图片", "images", image_failures if 'image_failures' in locals() else Counter()),
        (export_files, "文件", "files", file_failures if 'file_failures' in locals() else Counter()),
        (export_voices, "语音", "voices", voice_failures if 'voice_failures' in locals() else Counter()),
        (export_videos, "视频", "videos", video_failures if 'video_failures' in locals() else Counter()),
    ]
    for enabled, label, key, failures in summaries:
        if not enabled:
            continue
        requested = media_stats[f"{key}_requested"]
        exported = media_stats[f"{key}_exported"]
        log(f"{label}：{exported}/{requested} 已导出")
        if failures:
            summary = "；".join(f"{count}× {reason}" for reason, count in failures.most_common(3))
            log(f"{label}提示：{summary}")
    if export_voices:
        log(f"语音 WAV：{media_stats['voices_decoded']}/{media_stats['voices_exported']}")
    if transcribe_voices:
        log(
            f"语音转文字：{media_stats['voice_transcripts']}/{media_stats['voices_requested']}；"
            f"本地识别 {media_stats['voice_transcripts_local']}；"
            f"复用缓存 {media_stats['voice_transcripts_cached']}；"
            f"失败 {media_stats['voice_transcripts_failed']}"
        )
        if 'asr_failures' in locals() and asr_failures:
            summary = "；".join(
                f"{count}× {reason}"
                for reason, count in asr_failures.most_common(3)
            )
            log(f"语音转文字提示：{summary}")

    return {
        "chat_name": target_name,
        "is_group": is_group,
        "message_count": len(parsed),
        "media_stats": media_stats,
        "output_dir": str(chat_dir.resolve()),
        "txt": str(txt_path.resolve()),
        "md": str(md_path.resolve()),
        "json": str(json_path.resolve()),
    }
