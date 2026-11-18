# -*- coding: utf-8 -*-
"""用 main 分支（改动前）的代码导出指定会话，作为回归对照基线。

用法：python old_runner.py <旧代码目录> <输出目录> <username...>
输出一行 JSON：{username: {"json": ..., "txt": ..., "md": ..., "message_count": n}}
"""
import json
import sys
from pathlib import Path

old_tree = Path(sys.argv[1]).resolve()
out_root = Path(sys.argv[2]).resolve()
targets = sys.argv[3:]
sys.path.insert(0, str(old_tree))

import exporter_core as core  # noqa: E402  (main 分支版本)

workdir = core._create_sensitive_workdir()
results = {}
try:
    with core._upstream_sensitive_sandbox(workdir):
        db = core.WeChatDB(db_dir=None, workdir=str(workdir))
        chats, _ = core._batch_chat_candidates(db)
        by_username = {c["username"]: c for c in chats}
        cache = {}
        for username in targets:
            contact = by_username[username]
            r = core._export_chat_impl(
                out_root=out_root,
                db=db,
                contact=contact,
                folder_name=core._stable_batch_folder(username),
                index_cache=cache,
            )
            results[username] = {
                "json": r["json"], "txt": r["txt"], "md": r["md"],
                "message_count": r["message_count"],
            }
finally:
    ok, err = core._cleanup_sensitive_workdir(workdir)
results["__cleanup__"] = {"ok": ok, "error": err}
sys.stdout.reconfigure(encoding="utf-8")
print(json.dumps(results, ensure_ascii=False))
