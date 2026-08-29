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

        # Thumbnail cache avoids decoding the same image again when loading older pages.
        self.image_cache = {}
        self.embedded_widgets = []

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

        controls = ttk.Frame(top)
        controls.grid(row=0, column=1, sticky="e")

        self.load_btn = ttk.Button(
            controls,
            text="加载更早消息",
            command=self._load_older,
        )
        self.load_btn.pack(side="left", padx=(0, 12))

        self.count_label = ttk.Label(controls, text="")
        self.count_label.pack(side="left")

        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        # Use a native Text widget instead of hundreds of nested Frames on a Canvas.
        # It scrolls much more smoothly for long chats and avoids transparent ttk
        # areas exposing a black Canvas background on some Windows themes.
        bg = self.cget("background")
        self.text = tk.Text(
            body,
            wrap="word",
            undo=False,
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
            background=bg,
            foreground="black",
            insertbackground="black",
            padx=22,
            pady=12,
            spacing1=0,
            spacing2=0,
            spacing3=0,
            cursor="arrow",
        )
        self.scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        self._configure_tags()

        self.protocol("WM_DELETE_WINDOW", self._close)
        self._render()
        self.after(80, lambda: self.text.yview_moveto(1.0))

    def _configure_tags(self):
        self.text.tag_configure(
            "date",
            font=("Microsoft YaHei UI", 10, "bold"),
            justify="center",
            spacing1=14,
            spacing3=8,
        )
        self.text.tag_configure(
            "sender",
            font=("Microsoft YaHei UI", 10, "bold"),
            spacing1=10,
            spacing3=3,
        )
        self.text.tag_configure(
            "content",
            font=("Microsoft YaHei UI", 10),
            lmargin1=0,
            lmargin2=0,
            spacing3=4,
        )
        self.text.tag_configure(
            "transcript",
            font=("Microsoft YaHei UI", 9),
            foreground="#555555",
            lmargin1=16,
            lmargin2=16,
            spacing3=4,
        )
        self.text.tag_configure(
            "separator",
            foreground="#A8A8A8",
            spacing1=4,
            spacing3=4,
        )

    def _close(self):
        self.image_cache.clear()
        self.embedded_widgets.clear()
        self.destroy()

    def _set_editable(self, editable: bool):
        self.text.configure(state="normal" if editable else "disabled")

    def _render(self):
        # Rebuilding a Text document is cheap even for hundreds/thousands of
        # normal text messages, unlike rebuilding thousands of nested widgets.
        self._set_editable(True)
        self.text.delete("1.0", "end")
        self.embedded_widgets.clear()

        shown = len(self.messages) - self.start_index
        self.count_label.configure(text=f"显示 {shown}/{len(self.messages)} 条")

        remaining = self.start_index
        if remaining > 0:
            n = min(self.PAGE_SIZE, remaining)
            self.load_btn.configure(
                state="normal",
                text=f"加载更早 {n} 条消息",
            )
        else:
            self.load_btn.configure(
                state="disabled",
                text="已加载全部消息",
            )

        last_date = None
        for msg in self.messages[self.start_index:]:
            time_text = str(msg.get("time") or "")
            date = time_text[:10] if len(time_text) >= 10 else ""
            if date and date != last_date:
                if self.text.index("end-1c") != "1.0":
                    self.text.insert("end", "\n")
                self.text.insert("end", f"{date}\n", "date")
                last_date = date
            self._render_message(msg)

        self._set_editable(False)

    def _load_older(self):
        if self.start_index <= 0:
            return
        self.start_index = max(0, self.start_index - self.PAGE_SIZE)
        self._render()
        # New page starts at the top so the newly loaded older messages are visible.
        self.after_idle(lambda: self.text.yview_moveto(0.0))

    def _render_message(self, msg):
        time_text = str(msg.get("time") or "")
        time_only = time_text[11:19] if len(time_text) >= 19 else time_text
        sender = msg.get("sender") or "未知"

        self.text.insert("end", f"{time_only} | {sender}\n", "sender")

        content = str(msg.get("content") or "")
        if content and content not in {"[图片]", "[语音]", "[视频]"}:
            self.text.insert("end", content.rstrip() + "\n", "content")

        media = msg.get("media") or {}
        if media.get("available") and media.get("path"):
            full = self.chat_dir / Path(media["path"])
            kind = media.get("kind")
            if kind == "image":
                self._render_image(full)
            elif kind == "file":
                label = media.get("name") or full.name
                self._insert_button(
                    f"打开文件：{label}",
                    lambda p=full: self._open_path(p),
                )
            elif kind == "voice":
                label = "播放语音" if full.suffix.lower() == ".wav" else "打开语音文件"
                self._insert_button(
                    label,
                    lambda p=full: self._open_path(p),
                )
            elif kind == "video":
                self._insert_button(
                    "播放视频",
                    lambda p=full: self._open_path(p),
                )

        transcript = msg.get("transcript") or media.get("transcript")
        if transcript:
            source = msg.get("transcript_source") or media.get("transcript_source")
            label = "语音转文字（本地识别）" if source == "local_asr" else "语音转文字"
            self.text.insert(
                "end",
                f"{label}：{transcript}\n",
                "transcript",
            )

        # A lightweight text separator avoids creating one widget per message.
        self.text.insert("end", "─" * 92 + "\n", "separator")

    def _insert_button(self, text, command):
        button = ttk.Button(self.text, text=text, command=command)
        self.embedded_widgets.append(button)
        self.text.window_create("end", window=button, padx=0, pady=4)
        self.text.insert("end", "\n")

    def _render_image(self, path: Path):
        if not path.exists():
            self.text.insert("end", "[图片文件不存在]\n", "content")
            return

        key = str(path.resolve()).lower()
        photo = self.image_cache.get(key)
        if photo is None:
            try:
                with Image.open(path) as im:
                    image = im.convert("RGB")
                    image.thumbnail((600, 420), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(image)
                self.image_cache[key] = photo
            except Exception:
                self._insert_button(
                    "打开图片",
                    lambda p=path: self._open_path(p),
                )
                return

        # Only image messages create a small widget; normal text messages no longer do.
        label = tk.Label(
            self.text,
            image=photo,
            borderwidth=0,
            highlightthickness=0,
            cursor="hand2",
            background=self.text.cget("background"),
        )
        label.bind("<Button-1>", lambda _e, p=path: self._open_path(p))
        self.embedded_widgets.append(label)
        self.text.window_create("end", window=label, padx=0, pady=5)
        self.text.insert("end", "\n")

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
