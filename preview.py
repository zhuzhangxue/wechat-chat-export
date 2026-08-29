# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageTk


class ChatPreview(tk.Toplevel):
    PAGE_SIZE = 100

    def __init__(self, parent, json_path):
        super().__init__(parent)
        self.title("聊天预览")
        self.geometry("920x720")
        self.minsize(720, 520)

        self.json_path = Path(json_path)
        self.chat_dir = self.json_path.parent
        with self.json_path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)

        self.chat_name = data.get("chat_name") or self.chat_dir.name
        self.messages = data.get("messages") or []
        self.start_index = max(0, len(self.messages) - self.PAGE_SIZE)
        self.photo_refs = []

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        top = ttk.Frame(self, padding=(14, 12, 14, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)

        ttk.Label(
            top,
            text=self.chat_name,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.count_label = ttk.Label(top, text="")
        self.count_label.grid(row=0, column=1, sticky="e", padx=(10, 0))

        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(body, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        self.inner = ttk.Frame(self.canvas, padding=(18, 10, 18, 18))
        self.inner_window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self.protocol("WM_DELETE_WINDOW", self._close)
        self._render()
        self.after(80, lambda: self.canvas.yview_moveto(1.0))

    def _close(self):
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        self.destroy()

    def _on_inner_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.inner_window, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _clear(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self.photo_refs.clear()

    def _render(self):
        self._clear()
        shown = len(self.messages) - self.start_index
        self.count_label.configure(text=f"显示 {shown}/{len(self.messages)} 条")

        if self.start_index > 0:
            ttk.Button(
                self.inner,
                text=f"加载更早 {min(self.PAGE_SIZE, self.start_index)} 条消息",
                command=self._load_older,
            ).pack(pady=(0, 14))

        last_date = None
        for msg in self.messages[self.start_index:]:
            time_text = str(msg.get("time") or "")
            date = time_text[:10] if len(time_text) >= 10 else ""
            if date and date != last_date:
                ttk.Label(
                    self.inner,
                    text=date,
                    font=("Microsoft YaHei UI", 10, "bold"),
                ).pack(pady=(10, 8))
                last_date = date
            self._render_message(msg)

    def _load_older(self):
        self.start_index = max(0, self.start_index - self.PAGE_SIZE)
        self._render()
        self.after(50, lambda: self.canvas.yview_moveto(0.0))

    def _render_message(self, msg):
        card = ttk.Frame(self.inner, padding=(10, 8))
        card.pack(fill="x", pady=4)

        time_text = str(msg.get("time") or "")
        time_only = time_text[11:19] if len(time_text) >= 19 else time_text
        sender = msg.get("sender") or "未知"
        ttk.Label(
            card,
            text=f"{time_only} | {sender}",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(anchor="w")

        content = str(msg.get("content") or "")
        if content and content not in {"[图片]", "[语音]", "[视频]"}:
            ttk.Label(
                card,
                text=content,
                justify="left",
                wraplength=760,
            ).pack(anchor="w", pady=(4, 2))

        media = msg.get("media") or {}
        if media.get("available") and media.get("path"):
            full = self.chat_dir / Path(media["path"])
            kind = media.get("kind")
            if kind == "image":
                self._render_image(card, full)
            elif kind == "file":
                label = media.get("name") or full.name
                ttk.Button(
                    card,
                    text=f"打开文件：{label}",
                    command=lambda p=full: self._open_path(p),
                ).pack(anchor="w", pady=(5, 2))
            elif kind == "voice":
                label = "播放语音" if full.suffix.lower() == ".wav" else "打开语音文件"
                ttk.Button(
                    card,
                    text=label,
                    command=lambda p=full: self._open_path(p),
                ).pack(anchor="w", pady=(5, 2))
            elif kind == "video":
                ttk.Button(
                    card,
                    text="播放视频",
                    command=lambda p=full: self._open_path(p),
                ).pack(anchor="w", pady=(5, 2))

        transcript = msg.get("transcript") or media.get("transcript")
        if transcript:
            source = msg.get("transcript_source") or media.get("transcript_source")
            label = "语音转文字（本地识别）" if source == "local_asr" else "语音转文字"
            ttk.Label(
                card,
                text=f"{label}：{transcript}",
                justify="left",
                wraplength=760,
            ).pack(anchor="w", pady=(4, 2))

        ttk.Separator(card).pack(fill="x", pady=(8, 0))

    def _render_image(self, parent, path: Path):
        if not path.exists():
            ttk.Label(parent, text="[图片文件不存在]").pack(anchor="w", pady=4)
            return
        try:
            with Image.open(path) as im:
                image = im.convert("RGB")
                image.thumbnail((600, 420), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
        except Exception:
            ttk.Button(
                parent,
                text="打开图片",
                command=lambda p=path: self._open_path(p),
            ).pack(anchor="w", pady=4)
            return
        self.photo_refs.append(photo)
        label = ttk.Label(parent, image=photo, cursor="hand2")
        label.pack(anchor="w", pady=(6, 2))
        label.bind("<Button-1>", lambda _e, p=path: self._open_path(p))

    def _open_path(self, path: Path):
        if not path.exists():
            messagebox.showwarning("聊天预览", f"文件不存在：\n{path}", parent=self)
            return
        try:
            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror("聊天预览", f"无法打开：\n{exc}", parent=self)


def open_chat_preview(parent, json_path):
    path = Path(json_path)
    if not path.exists():
        messagebox.showwarning("聊天预览", "没有找到导出的 JSON。", parent=parent)
        return None
    return ChatPreview(parent, path)
