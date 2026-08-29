# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import psutil

from exporter_core import export_chat

APP_TITLE = "微信聊天导出给大模型"
WECHAT_PROCESS_NAMES = {"weixin.exe", "wechat.exe"}


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def is_wechat_running() -> bool:
    """检测 Windows 微信是否正在运行。"""
    try:
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name in WECHAT_PROCESS_NAMES:
                return True
    except (psutil.Error, OSError):
        # 检测本身异常时不阻断导出，让底层给出真实错误。
        return True
    return False


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("680x455")
        self.minsize(620, 415)

        self.q = queue.Queue()
        self.last_output = None

        pad = ttk.Frame(self, padding=18)
        pad.pack(fill="both", expand=True)

        ttk.Label(
            pad,
            text="微信聊天信息 → 大模型可读 TXT / JSON",
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(anchor="w")

        tk.Label(
            pad,
            text="⚠ 使用前请先登录 Windows 微信，并保持微信在后台运行。",
            fg="#b45309",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(anchor="w", pady=(8, 2))

        ttk.Label(
            pad,
            text="支持私聊与群聊。输入准确备注名、昵称或群名；程序会自动识别。",
        ).pack(anchor="w", pady=(2, 16))

        row = ttk.Frame(pad)
        row.pack(fill="x")

        ttk.Label(row, text="好友 / 群聊：").pack(side="left")
        self.name_var = tk.StringVar()
        self.entry = ttk.Entry(row, textvariable=self.name_var)
        self.entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.entry.bind("<Return>", lambda e: self.start_export())

        self.export_btn = ttk.Button(row, text="开始导出", command=self.start_export)
        self.export_btn.pack(side="left")

        outrow = ttk.Frame(pad)
        outrow.pack(fill="x", pady=(12, 8))
        ttk.Label(outrow, text="输出目录：").pack(side="left")
        self.out_var = tk.StringVar(value=str(app_dir() / "exports"))
        ttk.Entry(outrow, textvariable=self.out_var).pack(
            side="left", fill="x", expand=True, padx=(8, 8)
        )
        ttk.Button(outrow, text="选择", command=self.choose_out).pack(side="left")

        ttk.Separator(pad).pack(fill="x", pady=10)

        self.status = tk.Text(pad, height=12, wrap="word", state="disabled")
        self.status.pack(fill="both", expand=True)

        bottom = ttk.Frame(pad)
        bottom.pack(fill="x", pady=(10, 0))
        self.open_btn = ttk.Button(
            bottom,
            text="打开导出文件夹",
            command=self.open_output,
            state="disabled",
        )
        self.open_btn.pack(side="right")

        self.entry.focus_set()
        self.after(100, self.poll_queue)

    def choose_out(self):
        path = filedialog.askdirectory(
            initialdir=self.out_var.get() or str(app_dir())
        )
        if path:
            self.out_var.set(path)

    def log(self, msg):
        self.status.configure(state="normal")
        self.status.insert("end", str(msg) + "\n")
        self.status.see("end")
        self.status.configure(state="disabled")

    def start_export(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning(APP_TITLE, "请输入好友备注名、昵称或群名。")
            return

        if not is_wechat_running():
            self.log("未检测到正在运行的 Windows 微信。")
            messagebox.showwarning(
                APP_TITLE,
                "未检测到正在运行的 Windows 微信。\n\n"
                "请先启动并登录微信，保持微信在后台运行，然后重新开始导出。",
            )
            return

        self.export_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.last_output = None
        self.log("")
        self.log(f"开始导出：{name}")

        thread = threading.Thread(
            target=self.worker,
            args=(
                name,
                self.out_var.get().strip() or str(app_dir() / "exports"),
            ),
            daemon=True,
        )
        thread.start()

    def worker(self, name, outdir):
        try:
            result = export_chat(
                name,
                outdir,
                progress=lambda m: self.q.put(("log", m)),
            )
            self.q.put(("done", result))
        except Exception as e:
            self.q.put(("error", f"{type(e).__name__}: {e}"))

    def poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "done":
                    self.last_output = payload["output_dir"]
                    self.log(f"输出：{payload['output_dir']}")
                    self.export_btn.configure(state="normal")
                    self.open_btn.configure(state="normal")
                    messagebox.showinfo(
                        APP_TITLE,
                        f"导出完成。\n\n"
                        f"类型：{'群聊' if payload['is_group'] else '私聊'}\n"
                        f"消息数：{payload['message_count']}\n"
                        f"会话：{payload['chat_name']}",
                    )
                elif kind == "error":
                    self.export_btn.configure(state="normal")
                    self.log("导出失败：" + payload)
                    messagebox.showerror(
                        APP_TITLE,
                        "导出失败：\n\n" + payload,
                    )
        except queue.Empty:
            pass

        self.after(100, self.poll_queue)

    def open_output(self):
        if not self.last_output:
            return
        path = Path(self.last_output)
        if path.exists():
            os.startfile(str(path))


if __name__ == "__main__":
    App().mainloop()
