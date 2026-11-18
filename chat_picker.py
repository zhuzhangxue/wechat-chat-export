# -*- coding: utf-8 -*-
"""多选会话对话框：搜索、按类型筛选、勾选多个私聊 / 群聊后一次导出。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

CHECKED = "☑"
UNCHECKED = "☐"
KIND_ALL = "全部"
KIND_PRIVATE = "私聊"
KIND_GROUP = "群聊"


def filter_chats(chats, query="", kind=KIND_ALL):
    """按名称 / username 关键字（不区分大小写）和类型过滤，保持原顺序。"""
    needle = (query or "").strip().casefold()
    out = []
    for item in chats:
        if kind == KIND_PRIVATE and item["is_group"]:
            continue
        if kind == KIND_GROUP and not item["is_group"]:
            continue
        if needle:
            hay = f"{item.get('name') or ''}\n{item['username']}".casefold()
            if needle not in hay:
                continue
        out.append(item)
    return out


class ChatPicker(tk.Toplevel):
    def __init__(self, parent, chats, on_confirm, on_refresh=None, selected=None,
                 title="选择要导出的聊天"):
        super().__init__(parent)
        self.title(title)
        self.geometry("820x600")
        self.minsize(680, 460)
        self.transient(parent)

        self.chats = list(chats)
        self.known = {item["username"] for item in self.chats}
        self.selected = {u for u in (selected or ()) if u in self.known}
        self.on_confirm = on_confirm
        self.on_refresh = on_refresh
        self.visible = []

        pad = ttk.Frame(self, padding=12)
        pad.pack(fill="both", expand=True)
        pad.grid_columnconfigure(0, weight=1)
        pad.grid_rowconfigure(1, weight=1)

        top = ttk.Frame(pad)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.grid_columnconfigure(1, weight=1)
        ttk.Label(top, text="搜索：").grid(row=0, column=0, sticky="w")
        self.query_var = tk.StringVar()
        search = ttk.Entry(top, textvariable=self.query_var)
        search.grid(row=0, column=1, sticky="ew", padx=(4, 8))
        self.kind_var = tk.StringVar(value=KIND_ALL)
        kind_box = ttk.Combobox(
            top, textvariable=self.kind_var, width=6, state="readonly",
            values=(KIND_ALL, KIND_PRIVATE, KIND_GROUP),
        )
        kind_box.grid(row=0, column=2, padx=(0, 8))
        if on_refresh is not None:
            ttk.Button(top, text="刷新列表", command=self._refresh).grid(row=0, column=3)

        table = ttk.Frame(pad)
        table.grid(row=1, column=0, sticky="nsew")
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table, columns=("check", "name", "kind", "last"),
            show="headings", selectmode="extended",
        )
        self.tree.heading("check", text="选")
        self.tree.heading("name", text="名称")
        self.tree.heading("kind", text="类型")
        self.tree.heading("last", text="最近消息")
        self.tree.column("check", width=40, anchor="center", stretch=False)
        self.tree.column("name", width=380)
        self.tree.column("kind", width=60, anchor="center", stretch=False)
        self.tree.column("last", width=190, anchor="center", stretch=False)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        ttk.Label(
            pad,
            text="点击一行勾选 / 取消；Shift / Ctrl 选中多行后按空格可一起切换。搜索不会丢失已勾选的会话。",
            foreground="#6b7280",
            wraplength=760,
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))

        self.count_var = tk.StringVar()
        ttk.Label(pad, textvariable=self.count_var).grid(row=3, column=0, sticky="w", pady=(4, 0))

        bottom = ttk.Frame(pad)
        bottom.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        bottom.grid_columnconfigure(3, weight=1)
        ttk.Button(bottom, text="勾选当前列表", command=self._check_visible).grid(row=0, column=0)
        ttk.Button(bottom, text="取消当前列表", command=self._uncheck_visible).grid(
            row=0, column=1, padx=(6, 0)
        )
        ttk.Button(bottom, text="清空勾选", command=self._clear).grid(row=0, column=2, padx=(6, 0))
        self.confirm_btn = ttk.Button(bottom, text="导出选中", command=self._confirm)
        self.confirm_btn.grid(row=0, column=4)
        ttk.Button(bottom, text="取消", command=self.destroy).grid(row=0, column=5, padx=(6, 0))

        self.query_var.trace_add("write", lambda *_: self._render())
        kind_box.bind("<<ComboboxSelected>>", lambda _e: self._render())
        self.tree.bind("<ButtonRelease-1>", self._on_click)
        self.tree.bind("<space>", self._on_space)
        self.bind("<Escape>", lambda _e: self.destroy())

        self._render()
        search.focus_set()

    # ---- rendering ----
    def _render(self):
        self.tree.delete(*self.tree.get_children())
        self.visible = filter_chats(self.chats, self.query_var.get(), self.kind_var.get())
        for item in self.visible:
            self.tree.insert(
                "", "end", iid=item["username"],
                values=(
                    CHECKED if item["username"] in self.selected else UNCHECKED,
                    item.get("name") or item["username"],
                    KIND_GROUP if item["is_group"] else KIND_PRIVATE,
                    item.get("last_time_text") or "—",
                ),
            )
        self._update_count()

    def _refresh_row(self, username):
        if self.tree.exists(username):
            self.tree.set(username, "check", CHECKED if username in self.selected else UNCHECKED)

    def _update_count(self):
        hidden = len(self.selected - {item["username"] for item in self.visible})
        text = f"已选 {len(self.selected)} 个 · 当前显示 {len(self.visible)}/{len(self.chats)}"
        if hidden:
            text += f"（{hidden} 个已选不在当前筛选中）"
        self.count_var.set(text)
        self.confirm_btn.configure(state="normal" if self.selected else "disabled")

    # ---- toggling ----
    def toggle(self, usernames):
        usernames = [u for u in usernames if u in self.known]
        if not usernames:
            return
        # 混合状态时统一勾上；全部已勾时统一取消。
        if all(u in self.selected for u in usernames):
            self.selected.difference_update(usernames)
        else:
            self.selected.update(usernames)
        for username in usernames:
            self._refresh_row(username)
        self._update_count()

    def _on_click(self, event):
        if event.state & 0x0005:  # Shift / Ctrl：只做行选择，不切换
            return
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        row = self.tree.identify_row(event.y)
        if row:
            self.toggle([row])

    def _on_space(self, _event):
        self.toggle(list(self.tree.selection()))
        return "break"

    def _check_visible(self):
        self.selected.update(item["username"] for item in self.visible)
        self._render()

    def _uncheck_visible(self):
        self.selected.difference_update(item["username"] for item in self.visible)
        self._render()

    def _clear(self):
        self.selected.clear()
        self._render()

    # ---- actions ----
    def selected_in_order(self):
        return [item["username"] for item in self.chats if item["username"] in self.selected]

    def _confirm(self):
        chosen = self.selected_in_order()
        if not chosen:
            return
        self.destroy()
        self.on_confirm(chosen)

    def _refresh(self):
        keep = set(self.selected)
        self.destroy()
        self.on_refresh(keep)
