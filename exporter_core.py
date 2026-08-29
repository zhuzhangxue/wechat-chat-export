# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import html
import io
import json
import re
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET

import zstandard as zstd
from wechatauto import WeChatDB

APP_VERSION = "1.1.0"
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
    positions = [p for p in (text.find("<msg"), text.find("<appmsg"), text.find("<sysmsg")) if p >= 0]
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
    starts = [p for p in (
        candidate.find("<msg"),
        candidate.find("<appmsg"),
        candidate.find("<sysmsg")
    ) if p >= 0]
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
        ref_name = clean_text(refer.findtext("displayname") or "") if refer is not None else ""
        ref_content = clean_text(refer.findtext("content") or "") if refer is not None else ""
        ref_type = clean_text(refer.findtext("type") or "") if refer is not None else ""

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
            content = clean_text(re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1)))
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


def parse_content(raw_type, message_content, compress_content=None, group_prefix_strip=False) -> str:
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
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def load_rows(db: WeChatDB, username: str):
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
            cur = conn.execute("SELECT " + ", ".join(select_cols) + f" FROM {table}")
            names = [d[0] for d in cur.description]
            for row in cur.fetchall():
                item = dict(zip(names, row))
                for c in wanted:
                    item.setdefault(c, None)
                rows.append(item)
        finally:
            conn.close()

    rows.sort(key=lambda r: ((r.get("sort_seq") or 0), (r.get("local_id") or 0)))
    return rows


def fmt_time(ts) -> str:
    try:
        value = int(ts)
        if value > 10_000_000_000:
            value //= 1000
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts or "")


def resolve_sender(db: WeChatDB, row, is_group, target_name, sender_index, nicks, self_nick):
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
        return f"成员#{sid}" if sid not in (None, "") else "未知成员", False

    if not resolved or resolved == str(sid):
        return target_name, False
    return resolved, False


def export_chat(keyword: str, out_root="exports", progress=None):
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
        })
        if progress and idx % 2000 == 0:
            log(f"已处理 {idx}/{len(rows)} 条消息…")

    out_root = Path(out_root)
    chat_dir = out_root / safe_folder_name(target_name)
    chat_dir.mkdir(parents=True, exist_ok=True)

    txt_path = chat_dir / "chat_full_for_llm.txt"
    json_path = chat_dir / "chat_full_parsed.json"

    with txt_path.open("w", encoding="utf-8-sig", newline="\n") as f:
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

    with json_path.open("w", encoding="utf-8-sig") as f:
        json.dump({
            "exporter_version": APP_VERSION,
            "chat_type": "group" if is_group else "private",
            "chat_name": target_name,
            "message_count": len(parsed),
            "type_counts": type_counts,
            "messages": parsed,
        }, f, ensure_ascii=False, indent=2)

    log(f"完成：{len(parsed)} 条消息")
    return {
        "chat_name": target_name,
        "is_group": is_group,
        "message_count": len(parsed),
        "output_dir": str(chat_dir.resolve()),
        "txt": str(txt_path.resolve()),
        "json": str(json_path.resolve()),
    }
