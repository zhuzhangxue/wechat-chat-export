# -*- coding: utf-8 -*-
"""图形界面端到端：真实读取聊天列表 → 选择窗口勾选 2 个会话 → 填时间段 → 导出 → 完成弹窗。

弹窗被拦截记录（不阻塞）；结果只写计数到 gui_report.json。
用法：python tools/real_env_check/gui_e2e.py [仓库目录]（需先运行 real_env_check.py）
"""
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

REPO = (Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]).resolve()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
import app as appmod  # noqa: E402

details = json.loads((HERE / "private" / "private_details.json").read_text(encoding="utf-8"))
targets = [details["targets"]["私聊A"], details["targets"]["群聊G"]]
out_dir = HERE / "private" / "gui_out"

dialogs = []
result = {"steps": []}
deadline = time.time() + 300


def record(kind):
    def _f(title, message, *a, **k):
        dialogs.append({"kind": kind, "message": message})
        return True
    return _f


def step(name, ok=True, **extra):
    result["steps"].append({"step": name, "ok": bool(ok), **extra})
    print(("PASS " if ok else "FAIL ") + name, extra)


with patch.multiple(appmod.messagebox, showinfo=record("info"), showwarning=record("warning"),
                    showerror=record("error"), askyesno=record("askyesno")):
    win = appmod.App()
    win.out_var.set(str(out_dir))
    win.images_var.set(False)
    win.files_var.set(False)
    win.ranges_text.insert("1.0", "2020-01-01 ~\n")  # 一个开放时间段：验证界面把时间段传到导出

    def start():
        step("点击“多选导出…”", True)
        win.start_multi_select()
        win.after(300, wait_picker)

    def wait_picker():
        if time.time() > deadline:
            return finish("等待选择窗口超时")
        if win._picker is not None and win._picker.winfo_exists():
            picker = win._picker
            step("选择窗口打开并载入真实聊天列表", len(picker.chats) > 0, chats=len(picker.chats))
            step("列表载入完成后导出按钮恢复可用",
                 str(win.export_btn["state"]) == "normal")
            picker.toggle(targets)
            step("勾选 2 个会话（1 私聊 + 1 群聊）", len(picker.selected) == 2)
            picker._confirm()
            step("点击“导出选中”后导出按钮被禁用", str(win.multi_btn["state"]) == "disabled")
            return win.after(500, wait_done)
        if any(d["kind"] == "error" for d in dialogs):
            return finish("读取聊天列表失败")
        win.after(300, wait_picker)

    def wait_done():
        if time.time() > deadline:
            return finish("等待导出完成超时")
        done = [d for d in dialogs if "选中聊天导出完成" in d["message"]]
        errors = [d for d in dialogs if d["kind"] == "error"]
        if done or errors:
            return finish(None if done else "导出弹出错误")
        win.after(500, wait_done)

    def finish(problem):
        if problem:
            step(problem, False)
        index = out_dir / "selected_chats_index.json"
        if index.exists():
            data = json.loads(index.read_text(encoding="utf-8-sig"))
            step("生成 selected_chats_index.json，导出 2 个、失败 0 个",
                 data["exported"] == 2 and data["failed"] == 0 and data["selection"] == "selected",
                 exported=data["exported"], failed=data["failed"], messages=data["total_messages"])
            step("界面填写的时间段已传入导出", bool(data.get("time_ranges")))
        done = [d for d in dialogs if "选中聊天导出完成" in d["message"]]
        step("完成弹窗为普通提示（敏感缓存清理成功，未出现清理失败警告）",
             bool(done) and done[0]["kind"] == "info" and "清理失败" not in done[0]["message"])
        step("导出结束后按钮恢复可用",
             str(win.multi_btn["state"]) == "normal" and str(win.export_btn["state"]) == "normal")
        root = Path(tempfile.gettempdir()) / "wechat-chat-export-sensitive"
        residual = len(list(root.glob("run-*"))) if root.exists() else 0
        step("界面进程仍在运行时没有残留 run-* 敏感目录", residual == 0, residual=residual)
        result["dialogs"] = [{"kind": d["kind"]} for d in dialogs]
        win.destroy()

    win.after(800, start)
    win.mainloop()

result["passed"] = all(s["ok"] for s in result["steps"])
(HERE / "gui_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
sys.exit(0 if result["passed"] else 1)
