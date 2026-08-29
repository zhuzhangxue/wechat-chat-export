# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

import zstandard as zstd
from wechatauto import MediaDownloader, WeChatDB

APP_VERSION = "1.2.0"
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
                "create_time", "message_content", "compress_content",
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


def _index_local_files(db: WeChatDB) -> dict[str, list[Path]]:
    base = Path(db.account_dir) / "msg" / "file"
    out: dict[str, list[Path]] = {}
    if not base.exists():
        return out
    try:
        for p in base.rglob("*"):
            if p.is_file():
                out.setdefault(p.name.casefold(), []).append(p)
    except OSError:
        pass
    return out


def _pick_file_candidate(candidates: list[Path], create_time) -> Path | None:
    if not candidates:
        return None
    month = ""
    try:
        value = int(create_time)
        if value > 10_000_000_000:
            value //= 1000
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

def _write_image_from_row(
    md: MediaDownloader,
    row: dict,
    username: str,
    image_index: dict[str, Path],
    image_dir: Path,
    image_keys,
):
    media_md5 = _extract_media_md5(row)
    if not media_md5:
        return None, "消息中没有找到图片 MD5"

    dat_path = image_index.get((media_md5 + ".dat").lower())
    variant = "original"
    if dat_path is None:
        dat_path = image_index.get((media_md5 + "_t.dat").lower())
        variant = "thumbnail"

    if dat_path is None:
        return None, "本机没有找到图片原图或缩略图缓存"

    aes_key = image_keys[0] if image_keys else None
    xor_key = image_keys[1] if image_keys else None

    try:
        with dat_path.open("rb") as fh:
            magic = fh.read(6)
    except OSError as exc:
        return None, f"图片缓存读取失败：{exc}"

    # 微信 4.x v2 图片需要 AES 密钥。若快速获取失败，直接跳过，
    # 避免上游进入每张图最长 120 秒的监控等待。
    if magic == b"\x07\x08\x56\x32\x08\x07" and not image_keys:
        return None, "未获取到图片解密密钥"

    try:
        data = md.decrypt_image(str(dat_path), aes_key=aes_key, xor_key=xor_key)
    except Exception as exc:
        return None, f"图片解密失败：{type(exc).__name__}: {exc}"

    if data[:3] == b"\xff\xd8\xff":
        ext = ".jpg"
    elif data[:4] == b"\x89PNG":
        ext = ".png"
    elif data[:3] == b"GIF":
        ext = ".gif"
    elif data[:4] == b"wxgf":
        try:
            jpg = md._wxgf_to_jpg(data)
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
    seq = row.get("sort_seq") or row.get("local_id") or "image"
    lid = row.get("local_id") or "0"
    suffix = "_thumb" if variant == "thumbnail" else ""
    out = image_dir / f"{seq}_{lid}{suffix}{ext}"

    try:
        out.write_bytes(data)
    except OSError as exc:
        return None, f"图片写入失败：{exc}"

    return {
        "kind": "image",
        "path": str(out),
        "variant": variant,
        "previewable": ext.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"},
    }, None


def _file_name_from_row(md: MediaDownloader, row: dict, parsed_content: str) -> str:
    media_row = {
        "server_id": row.get("server_id"),
    }
    try:
        name = md._file_name(media_row)
    except Exception:
        name = None

    if name:
        return safe_file_name(name, "file")

    if parsed_content.startswith("[文件]"):
        fallback = parsed_content[len("[文件]"):].strip()
        if fallback:
            return safe_file_name(fallback, "file")
    return ""


def _copy_file_from_row(
    md: MediaDownloader,
    row: dict,
    parsed_content: str,
    file_index: dict[str, list[Path]],
    file_dir: Path,
):
    name = _file_name_from_row(md, row, parsed_content)
    if not name:
        return None, "不是可定位的本地文件，或未解析到文件名"

    candidates = file_index.get(name.casefold(), [])
    src = _pick_file_candidate(candidates, row.get("create_time"))
    if src is None:
        return None, f"本机没有找到文件缓存：{name}"

    file_dir.mkdir(parents=True, exist_ok=True)
    seq = row.get("sort_seq") or row.get("local_id") or "file"
    lid = row.get("local_id") or "0"
    out = file_dir / f"{seq}_{lid}_{safe_file_name(name, 'file')}"

    try:
        if out.exists():
            out = file_dir / f"{seq}_{lid}_{src.stat().st_size}_{safe_file_name(name, 'file')}"
        shutil.copy2(src, out)
    except OSError as exc:
        return None, f"文件复制失败：{exc}"

    return {
        "kind": "file",
        "path": str(out),
        "name": name,
        "previewable": False,
    }, None


def _media_label(media: dict) -> str:
    if media.get("kind") == "image":
        return "图片"
    if media.get("kind") == "file":
        return "文件"
    return "附件"


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

            f.write(
                f"{m['time']} | {m['sender']}："
                f"{m['content'] or '[' + m['type'] + ']'}\n"
            )
            media = m.get("media")
            if media and media.get("available") and media.get("path"):
                f.write(f"    ↳ {_media_label(media)}：{media['path']}\n")


def _md_message_content(content: str) -> str:
    # 保留原始内容，只把换行换成 Markdown 硬换行。
    return (content or "").replace("\n", "  \n")


def _write_markdown(
    parsed: list[dict],
    path: Path,
    is_group: bool,
    target_name: str,
):
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

            content = _md_message_content(
                m["content"] or f"[{m['type']}]"
            )
            f.write(f"**{time_only} | {m['sender']}：** {content}\n\n")

            media = m.get("media")
            if not media or not media.get("available") or not media.get("path"):
                continue

            href = _markdown_href(media["path"])
            if media.get("kind") == "image":
                if media.get("previewable"):
                    alt = "图片"
                    if media.get("variant") == "thumbnail":
                        alt = "图片（缩略图）"
                    f.write(f"![{alt}]({href})\n\n")
                else:
                    f.write(f"[打开图片文件]({href})\n\n")
            elif media.get("kind") == "file":
                label = media.get("name") or Path(media["path"]).name
                label = label.replace("[", "\\[").replace("]", "\\]")
                f.write(f"[打开文件：{label}]({href})\n\n")


def export_chat(
    keyword: str,
    out_root="exports",
    progress=None,
    export_images=False,
    export_files=False,
):
    def log(msg):
        if progress:
            progress(msg)

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

        sender, used_group_prefix = resolve_sender(
            db, row, is_group, target_name, sender_index, nicks, self_nick
        )
        content = parse_content(
            raw_type,
            row.get("message_content"),
            row.get("compress_content"),
            group_prefix_strip=(is_group and used_group_prefix),
        )
        parsed.append({
            "local_id": row.get("local_id"),
            "type": TYPE_LABEL.get(t, str(t)),
            "type_code": raw_type,
            "sender": sender,
            "time": fmt_time(row.get("create_time")),
            "content": content,
            "sort_seq": row.get("sort_seq"),
            "media": None,
        })

        if progress and idx % 2000 == 0:
            log(f"已处理 {idx}/{len(rows)} 条消息…")

    media_stats = {
        "images_requested": 0,
        "images_exported": 0,
        "files_requested": 0,
        "files_exported": 0,
    }

    # 附件导出使用上游 MediaDownloader 的图片解密/文件名解析能力，
    # 但消息行沿用本项目自己的跨分片读取结果。
    if export_images or export_files:
        md = MediaDownloader(db)
        image_rows_exist = export_images and any(low_type(r.get("local_type")) == 3 for r in rows)
        file_rows_exist = export_files and any(
            low_type(r.get("local_type")) == 49
            and parse_content(
                r.get("local_type"),
                r.get("message_content"),
                r.get("compress_content"),
            ).startswith("[文件]")
            for r in rows
        )

        image_index = {}
        image_keys = None
        file_index = {}

        if image_rows_exist:
            log("正在定位本机图片缓存…")
            image_index = _index_image_files(db, username)
            if image_index:
                log("正在准备图片解密…")
                image_keys = _detect_image_keys_fast(md)
                if not image_keys:
                    log("未快速获取到图片解密密钥；可导出的旧格式图片仍会尝试处理。")
            else:
                log("该会话没有找到本机图片缓存。")

        if file_rows_exist:
            log("正在索引本机文件缓存…")
            file_index = _index_local_files(db)

        image_dir = chat_dir / "media" / "images"
        file_dir = chat_dir / "media" / "files"

        for idx, (row, msg) in enumerate(zip(rows, parsed), 1):
            t = low_type(row.get("local_type"))

            if export_images and t == 3:
                media_stats["images_requested"] += 1
                media, reason = _write_image_from_row(
                    md, row, username, image_index, image_dir, image_keys
                )
                if media:
                    rel = _relative_media_path(chat_dir, Path(media["path"]))
                    media["path"] = rel
                    media["available"] = True
                    msg["media"] = media
                    media_stats["images_exported"] += 1
                else:
                    msg["media"] = {
                        "kind": "image",
                        "available": False,
                        "path": None,
                        "reason": reason,
                    }

            elif export_files and t == 49 and msg["content"].startswith("[文件]"):
                media_stats["files_requested"] += 1
                media, reason = _copy_file_from_row(
                    md, row, msg["content"], file_index, file_dir
                )
                if media:
                    rel = _relative_media_path(chat_dir, Path(media["path"]))
                    media["path"] = rel
                    media["available"] = True
                    msg["media"] = media
                    media_stats["files_exported"] += 1
                else:
                    msg["media"] = {
                        "kind": "file",
                        "available": False,
                        "path": None,
                        "reason": reason,
                    }

            if progress and idx % 200 == 0 and (export_images or export_files):
                log(
                    "附件处理进度："
                    f"{idx}/{len(rows)}，"
                    f"图片 {media_stats['images_exported']}/{media_stats['images_requested']}，"
                    f"文件 {media_stats['files_exported']}/{media_stats['files_requested']}"
                )

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
    if export_images:
        log(
            f"图片：{media_stats['images_exported']}/"
            f"{media_stats['images_requested']} 已导出"
        )
    if export_files:
        log(
            f"文件：{media_stats['files_exported']}/"
            f"{media_stats['files_requested']} 已导出"
        )

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
