# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

WECHAT_DATA_SUBDIRS = ("xwechat_files", "WeChat Files", "xwechat_files_data")
_CONFIG_EXTS = {".ini", ".json", ".txt", ".cfg", ".conf", ".xml"}
_WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:[\\/][^\r\n\"'<>|?*]+)")


def _norm_key(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))




def _safe_is_dir(path: Path) -> bool:
    """Windows 某些受保护目录会让 is_dir/stat 抛 OSError，发现流程应直接跳过。"""
    try:
        return path.is_dir()
    except OSError:
        return False


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _clean_path(value: str | Path) -> Path:
    raw = os.path.expandvars(os.path.expanduser(str(value).strip().strip('"\'')))
    # JSON / 配置文件中常见的双反斜杠路径。
    raw = raw.replace("\\\\", "\\")
    return Path(raw)


def _account_dirs(root: Path) -> list[Path]:
    try:
        children = list(root.iterdir())
    except OSError:
        return []

    out: list[Path] = []
    for child in children:
        if not _safe_is_dir(child):
            continue
        if _safe_is_dir(child / "db_storage"):
            out.append(child)
    return out


def _resolve_account_root(path: str | Path) -> Path | None:
    """把候选路径规整到「账号目录的父目录」。"""
    try:
        base = _clean_path(path)
    except Exception:
        return None
    if not _safe_is_dir(base):
        return None

    candidates = [base]
    candidates.extend(base / name for name in WECHAT_DATA_SUBDIRS)

    for cand in candidates:
        if _safe_is_dir(cand) and _account_dirs(cand):
            return cand
    return None


def _latest_db_mtime(root: Path) -> float:
    latest = 0.0
    for account in _account_dirs(root):
        db_root = account / "db_storage"
        try:
            for cur, _, names in os.walk(db_root):
                for name in names:
                    if not (name.endswith(".db") or name.endswith(".db-wal")):
                        continue
                    try:
                        latest = max(latest, os.path.getmtime(os.path.join(cur, name)))
                    except OSError:
                        pass
        except OSError:
            pass
    return latest


def _inspect_root(root: Path, sources: set[str], auto_root: Path | None) -> dict:
    accounts = _account_dirs(root)
    latest = _latest_db_mtime(root)
    auto_selected = auto_root is not None and _norm_key(root) == _norm_key(auto_root)
    labels = set(sources)
    if auto_selected:
        labels.add("当前自动探测")
    latest_text = datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M") if latest else "未知"
    return {
        "path": str(root),
        "account_count": len(accounts),
        "latest_mtime": latest,
        "latest_text": latest_text,
        "auto_selected": auto_selected,
        "sources": "、".join(sorted(labels)),
    }


def _decode_config_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "ignore")


def _extract_strings_from_json(value) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            out.extend(_extract_strings_from_json(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_extract_strings_from_json(item))
    return out


def _extract_windows_paths(text: str) -> list[str]:
    values: list[str] = []
    try:
        obj = json.loads(text)
    except Exception:
        obj = None
    if obj is not None:
        values.extend(_extract_strings_from_json(obj))

    values.extend(m.group(0).strip() for m in _WINDOWS_PATH_RE.finditer(text))

    out: list[str] = []
    seen = set()
    for value in values:
        value = value.strip().strip('"\'').rstrip(";,)")
        value = value.replace("\\\\", "\\")
        if not re.match(r"(?i)^[a-z]:[\\/]", value):
            continue
        key = os.path.normcase(value)
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _config_candidate_paths() -> list[str]:
    result: list[str] = []
    roots: list[Path] = []
    for env_name in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if not base:
            continue
        roots.extend(
            [
                Path(base) / "Tencent" / "xwechat",
                Path(base) / "Tencent" / "xwechat" / "config",
                Path(base) / "Tencent" / "WeChat",
            ]
        )

    seen_files = set()
    for root in roots:
        if not _safe_is_dir(root):
            continue
        try:
            files = list(root.glob("*")) + list(root.glob("*/*"))
        except OSError:
            continue
        for file in files[:300]:
            if not _safe_is_file(file) or file.suffix.lower() not in _CONFIG_EXTS:
                continue
            key = _norm_key(file)
            if key in seen_files:
                continue
            seen_files.add(key)
            try:
                if file.stat().st_size > 2 * 1024 * 1024:
                    continue
                text = _decode_config_text(file.read_bytes())
            except OSError:
                continue
            result.extend(_extract_windows_paths(text))
    return result


def _registry_candidate_paths() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    result: list[str] = []
    for hive, sub in (
        (winreg.HKEY_CURRENT_USER, r"Software\Tencent\xwechat"),
        (winreg.HKEY_CURRENT_USER, r"Software\Tencent\xwechat\config"),
        (winreg.HKEY_CURRENT_USER, r"Software\Tencent\WeChat"),
    ):
        try:
            key = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                if not isinstance(data, str) or not data.strip():
                    continue
                low = name.lower()
                if "path" in low or "dir" in low or "save" in low:
                    result.append(data.strip())
        finally:
            winreg.CloseKey(key)
    return result


def _common_candidate_paths() -> list[Path]:
    home = Path.home()
    paths = [
        home / "Documents" / "xwechat_files",
        home / "Documents" / "WeChat Files",
        home / "xwechat_files",
        home / "WeChat Files",
    ]
    for env_name in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            paths.extend(
                [
                    Path(base) / "Tencent" / "xwechat",
                    Path(base) / "Tencent" / "WeChat Files",
                ]
            )
    return paths


def _fixed_drive_roots() -> list[Path]:
    if sys.platform != "win32":
        return []
    roots: list[Path] = []
    get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    for code in range(ord("A"), ord("Z") + 1):
        root = f"{chr(code)}:\\"
        try:
            if get_drive_type(root) == 3:  # DRIVE_FIXED
                roots.append(Path(root))
        except Exception:
            continue
    return roots


def _shallow_drive_candidates() -> list[Path]:
    """只扫固定磁盘根目录的一层，避免全盘递归带来的卡顿。"""
    out: list[Path] = []
    known_names = set(WECHAT_DATA_SUBDIRS) | {"WeChatData", "Tencent Files", "Tencent"}
    for drive in _fixed_drive_roots():
        for name in known_names:
            out.append(drive / name)
        try:
            raw_children = list(drive.iterdir())
        except OSError:
            continue
        # 根目录通常只有几十个目录；逐个容错，WindowsApps/WpSystem 等
        # 受保护目录可能在读取属性时直接抛 OSError。
        children: list[Path] = []
        for child in raw_children[:512]:
            if _safe_is_dir(child):
                children.append(child)
        for child in children[:256]:
            out.append(child)
    return out


def discover_wechat_data_dirs(current: str | None = None) -> list[dict]:
    """发现高可信微信数据目录候选，并按数据库最近修改时间排序。"""
    candidates: dict[str, dict] = {}

    auto_root: Path | None = None
    try:
        from wechatauto import auto_detect_db_dir

        auto = auto_detect_db_dir()
        auto_root = _resolve_account_root(auto) if auto else None
    except Exception:
        auto_root = None

    def add(value, source: str):
        if not value:
            return
        root = _resolve_account_root(value)
        if root is None:
            return
        key = _norm_key(root)
        entry = candidates.setdefault(key, {"root": root, "sources": set()})
        entry["sources"].add(source)

    add(current, "当前输入")
    if auto_root is not None:
        add(auto_root, "自动探测")

    for value in _config_candidate_paths():
        add(value, "微信配置")
    for value in _registry_candidate_paths():
        add(value, "注册表")
    for value in _common_candidate_paths():
        add(value, "常见位置")
    for value in _shallow_drive_candidates():
        add(value, "磁盘浅层扫描")

    rows = [
        _inspect_root(entry["root"], entry["sources"], auto_root)
        for entry in candidates.values()
    ]
    rows.sort(key=lambda item: (item["latest_mtime"], item["auto_selected"]), reverse=True)
    return rows


def _browse_other(parent, initial: str | None) -> str | None:
    start = initial if initial and _safe_is_dir(Path(initial)) else str(Path.home())
    path = filedialog.askdirectory(parent=parent, initialdir=start)
    return path or None


def choose_wechat_data_dir(parent, current: str | None = None) -> str | None:
    """先列出自动发现的候选目录，仍保留普通文件夹浏览作为兜底。"""
    old_cursor = parent.cget("cursor")
    try:
        parent.configure(cursor="watch")
        parent.update_idletasks()
        rows = discover_wechat_data_dirs(current)
    finally:
        parent.configure(cursor=old_cursor)

    if not rows:
        messagebox.showinfo(
            "微信数据目录",
            "没有自动发现可确认的微信数据目录。\n\n"
            "接下来可以手动浏览文件夹；通常选择微信“设置 → 文件管理”里显示的目录即可。",
            parent=parent,
        )
        return _browse_other(parent, current)

    result = {"path": None}
    win = tk.Toplevel(parent)
    win.title("选择微信数据目录")
    win.geometry("900x420")
    win.minsize(760, 330)
    win.transient(parent)
    win.grab_set()
    win.grid_rowconfigure(1, weight=1)
    win.grid_columnconfigure(0, weight=1)

    ttk.Label(
        win,
        text="已发现以下微信数据目录。按数据库最近修改时间排序，较新的通常更可能是正在使用的数据。",
        wraplength=840,
    ).grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))

    frame = ttk.Frame(win)
    frame.grid(row=1, column=0, sticky="nsew", padx=16)
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(0, weight=1)

    columns = ("path", "accounts", "latest", "source")
    tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
    tree.heading("path", text="目录")
    tree.heading("accounts", text="账号")
    tree.heading("latest", text="最新数据库")
    tree.heading("source", text="发现来源")
    tree.column("path", width=430, anchor="w")
    tree.column("accounts", width=60, anchor="center", stretch=False)
    tree.column("latest", width=135, anchor="center", stretch=False)
    tree.column("source", width=180, anchor="w")

    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")

    row_by_iid: dict[str, dict] = {}

    def populate(items: list[dict]):
        for iid in tree.get_children():
            tree.delete(iid)
        row_by_iid.clear()
        current_key = _norm_key(current) if current else None
        selected = None
        for idx, item in enumerate(items):
            source = item["sources"]
            if item["auto_selected"] and "当前自动探测" not in source:
                source = (source + "、当前自动探测").strip("、")
            iid = tree.insert(
                "",
                "end",
                values=(
                    item["path"],
                    item["account_count"],
                    item["latest_text"],
                    source,
                ),
            )
            row_by_iid[iid] = item
            if current_key and _norm_key(item["path"]) == current_key:
                selected = iid
            elif selected is None and idx == 0:
                selected = iid
        if selected:
            tree.selection_set(selected)
            tree.focus(selected)
            tree.see(selected)

    populate(rows)

    note = ttk.Label(
        win,
        text="这里只做高可信来源 + 固定磁盘浅层扫描，不会递归扫完整个硬盘。找不到时可点“浏览其他目录”。",
        foreground="#6b7280",
        wraplength=840,
    )
    note.grid(row=2, column=0, sticky="w", padx=16, pady=(8, 4))

    buttons = ttk.Frame(win)
    buttons.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 16))
    buttons.grid_columnconfigure(0, weight=1)

    def use_selected(event=None):
        selection = tree.selection()
        if not selection:
            return
        item = row_by_iid.get(selection[0])
        if item:
            result["path"] = item["path"]
            win.destroy()

    def browse_other():
        selection = tree.selection()
        initial = current
        if selection:
            item = row_by_iid.get(selection[0])
            if item:
                initial = item["path"]
        path = _browse_other(win, initial)
        if path:
            result["path"] = path
            win.destroy()

    def rescan():
        note.configure(text="正在重新扫描……")
        win.configure(cursor="watch")
        win.update_idletasks()
        try:
            new_rows = discover_wechat_data_dirs(current)
            populate(new_rows)
            note.configure(
                text=f"重新扫描完成，共发现 {len(new_rows)} 个候选。找不到时可点“浏览其他目录”。"
            )
        finally:
            win.configure(cursor="")

    ttk.Button(buttons, text="重新扫描", command=rescan).grid(row=0, column=1, padx=(0, 8))
    ttk.Button(buttons, text="浏览其他目录", command=browse_other).grid(row=0, column=2, padx=(0, 8))
    ttk.Button(buttons, text="取消", command=win.destroy).grid(row=0, column=3, padx=(0, 8))
    ttk.Button(buttons, text="使用选中目录", command=use_selected).grid(row=0, column=4)

    tree.bind("<Double-1>", use_selected)
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.wait_window()
    return result["path"]
