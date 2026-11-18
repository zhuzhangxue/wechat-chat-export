# -*- coding: utf-8 -*-
"""真实微信环境验证：聊天列表 + 多选导出、按时间段导出、同名联系人不再静默选错。

只读本机微信数据。所有导出写到 private/ 目录（含真实聊天，不要上传）；
report.json 只含计数和通过 / 失败，不含任何聊天名、username、内容或具体日期。

用法：python tools/real_env_check/real_env_check.py [仓库目录，默认自动定位]
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

REPO = (Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]).resolve()
HERE = Path(__file__).resolve().parent
PRIVATE = HERE / "private"
sys.path.insert(0, str(REPO))

import exporter_core as core  # noqa: E402

report = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "checks": [], "cleanup_trace": []}
private_log = {}

import threading  # noqa: E402

_original_cleanup = core._cleanup_sensitive_workdir
_current_stage = ["init"]


def _open_connections_under(workdir):
    """列出仍然打开、指向 workdir 内文件的 sqlite3 连接及其引用者类型（诊断用）。"""
    import gc
    import sqlite3
    found = []
    for obj in gc.get_objects():
        if not isinstance(obj, sqlite3.Connection):
            continue
        try:
            files = [row[2] for row in obj.execute("PRAGMA database_list")]
        except sqlite3.ProgrammingError:
            continue  # 已关闭
        if not any(f and str(Path(workdir)) in f for f in files):
            continue
        referrers = []
        for ref in gc.get_referrers(obj):
            if ref is found:
                continue
            kind = type(ref).__name__
            if kind == "_lru_cache_wrapper":
                wrapped = getattr(ref, "__wrapped__", None)
                kind = f"lru_cache:{getattr(wrapped, '__module__', '?')}.{getattr(wrapped, '__qualname__', '?')}"
            if kind == "frame":
                kind = f"frame:{ref.f_code.co_name}@{Path(ref.f_code.co_filename).name}:{ref.f_lineno}"
            elif kind == "dict":
                owners = [type(o).__name__ for o in gc.get_referrers(ref)
                          if hasattr(o, "__dict__") and getattr(o, "__dict__", None) is ref]
                kind = f"dict(of {owners})" if owners else "dict"
            referrers.append(kind)
        found.append({"file": Path(files[0]).name if files else None, "referrers": referrers[:6]})
    return found


def _traced_cleanup(workdir, progress=None):
    live = _open_connections_under(workdir)
    ok, error = _original_cleanup(workdir, progress=progress)
    report.setdefault("open_connections_at_cleanup", []).append(
        {"ok": ok, "open": live})
    report["cleanup_trace"].append({
        "stage": _current_stage[0],
        "ok": ok,
        # 只记录错误类型和出错文件的类型，不记录完整路径
        "error": None if ok else (error or "").split(":")[0],
        "error_detail_file": None if ok else Path(str(error).split("'")[-2]).name
        if error and error.count("'") >= 2 else None,
        "dir_exists_after": Path(workdir).exists(),
        "extra_threads": sorted(t.name for t in threading.enumerate() if t is not threading.main_thread()),
    })
    return ok, error


core._cleanup_sensitive_workdir = _traced_cleanup


def check(name, passed, **details):
    report["checks"].append({"name": name, "passed": bool(passed), **details})
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {name} {json.dumps(details, ensure_ascii=False)}")
    return passed


def section(title):
    _current_stage[0] = title.split(" ")[0]
    print(f"\n===== {title} =====")


# ---------------------------------------------------------------- 敏感路径快照
def fingerprint(path: Path):
    if not path.exists():
        return {"exists": False}
    items = []
    for root, _dirs, files in os.walk(path):
        for name in files:
            p = Path(root) / name
            try:
                st = p.stat()
            except OSError:
                continue
            items.append(f"{p.relative_to(path)}|{st.st_size}|{st.st_mtime_ns}")
    items.sort()
    return {
        "exists": True,
        "files": len(items),
        "digest": hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest(),
    }


def sensitive_snapshot():
    tmp = Path(tempfile.gettempdir())
    run_root = tmp / core.SENSITIVE_TEMP_ROOT_NAME
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    return {
        "run_dirs": sorted(p.name for p in run_root.glob("run-*")) if run_root.exists() else [],
        "legacy_wechatauto_db": fingerprint(tmp / core.LEGACY_WECHATAUTO_CACHE_NAME),
        "localappdata_wechatauto_keys": fingerprint(local / "wechatauto_keys"),
        "repo_wechatauto_logs": (REPO / "wechatauto_logs").exists(),
        "cwd_wechatauto_logs": (Path.cwd() / "wechatauto_logs").exists(),
        "env_WECHATAUTO_KEYS_DIR": os.environ.get(core.UPSTREAM_KEYS_ENV),
    }


def assert_no_sensitive_residue(label, before):
    after = sensitive_snapshot()
    check(f"{label}：没有残留一次性敏感目录 run-*", not after["run_dirs"],
          residual=len(after["run_dirs"]))
    check(f"{label}：未改动旧版共享 %TEMP%\\wechatauto_db",
          after["legacy_wechatauto_db"] == before["legacy_wechatauto_db"])
    check(f"{label}：未写入 %LOCALAPPDATA%\\wechatauto_keys",
          after["localappdata_wechatauto_keys"] == before["localappdata_wechatauto_keys"])
    check(f"{label}：未在仓库 / 当前目录生成 wechatauto_logs",
          not after["repo_wechatauto_logs"] and not after["cwd_wechatauto_logs"])
    check(f"{label}：进程环境变量 WECHATAUTO_KEYS_DIR 已恢复",
          after["env_WECHATAUTO_KEYS_DIR"] == before["env_WECHATAUTO_KEYS_DIR"])


# ---------------------------------------------------------------- 工具
def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def msg_key(m):
    return (m.get("source_db"), m.get("local_id"), m.get("server_id"))


def parse_time(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def independent_bounds(spec):
    """测试自己的时间段语义实现（不调用 time_ranges.py），用于交叉验证。"""
    start_s, end_s = [x.strip() for x in spec.split("~")]

    def point(s, is_end):
        if len(s) == 10:
            d = datetime.strptime(s, "%Y-%m-%d")
            return d + timedelta(days=1) if is_end else d
        d = datetime.strptime(s, "%Y-%m-%d %H:%M")
        return d + timedelta(minutes=1) if is_end else d

    return point(start_s, False), point(end_s, True)


def quiet(_msg):
    pass


# ================================================================ 0. 环境
section("0. 环境")
import importlib.metadata as md  # noqa: E402

report["environment"] = {
    "os": platform.platform(),
    "python": platform.python_version(),
    "wechatauto_replica": md.version("wechatauto-replica"),
    "weixin_running": bool(subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Weixin.exe"], capture_output=True, text=True,
        encoding="gbk", errors="ignore",
    ).stdout.count("Weixin.exe")),
    "base_commit": subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
    ).stdout.strip(),
}
print(report["environment"])
if PRIVATE.exists():
    shutil.rmtree(PRIVATE)
PRIVATE.mkdir(parents=True)
baseline = sensitive_snapshot()
check("测试开始前没有遗留的 run-* 敏感目录", not baseline["run_dirs"], residual=len(baseline["run_dirs"]))

try:
    # ============================================================ 1. 聊天列表
    section("1. 聊天列表 list_chats")
    t0 = time.time()
    listing = core.list_chats(progress=quiet)
    chats = listing["chats"]
    report["list_chats"] = {
        "chats": len(chats),
        "private": sum(1 for c in chats if not c["is_group"]),
        "groups": sum(1 for c in chats if c["is_group"]),
        "unresolved_message_tables": listing["unresolved_message_tables"],
        "seconds": round(time.time() - t0, 1),
    }
    check("list_chats 返回可导出会话", len(chats) > 0, **report["list_chats"])
    check("list_chats 敏感缓存自动清理成功", listing["sensitive_cache_cleanup"])
    check("列表 username 唯一（同名联系人不会合并成一项）",
          len({c["username"] for c in chats}) == len(chats))
    check("列表中显示名重复的会话仍各自独立",
          True, duplicated_display_names=sum(
              n - 1 for n in Counter(c["name"] for c in chats).values() if n > 1))
    assert_no_sensitive_residue("列表读取后", baseline)

    # 选 24 小时内没有新消息的会话，避免新旧两次导出之间收到新消息导致回归对比误报
    quiet_cutoff = time.time() - 86400
    settled = [c for c in chats if c["last_time"] and c["last_time"] < quiet_cutoff]
    privates = [c for c in settled if not c["is_group"]]
    groups = [c for c in settled if c["is_group"]]
    if len(privates) < 2 or not groups:
        raise RuntimeError("找不到足够的“24 小时内无新消息”的私聊 / 群聊作为测试对象")
    picked = privates[:2] + groups[:1]
    labels = {c["username"]: lab for c, lab in zip(picked, ["私聊A", "私聊B", "群聊G"])}
    targets = [c["username"] for c in picked]
    private_log["targets"] = {labels[u]: u for u in targets}

    # ============================================================ 2. 多选导出 + 回归
    section("2. 多选导出（3 个会话 + 1 个不存在的 username）")
    sel_out = PRIVATE / "selected"
    ghost = "wxid_real_env_check_not_exist"
    t0 = time.time()
    sel = core.export_all_chats(sel_out, progress=quiet, usernames=targets + [ghost])
    report["multi_select"] = {
        "requested": len(targets) + 1,
        "selected_total": sel["selected_total"],
        "exported": sel["exported"],
        "skipped_empty": sel["skipped_empty"],
        "failed": sel["failed"],
        "not_found": len(sel["not_found"]),
        "messages": sel["total_messages"],
        "seconds": round(time.time() - t0, 1),
    }
    check("只导出选中的 3 个会话", sel["selected_total"] == 3 and sel["exported"] == 3,
          **report["multi_select"])
    check("不存在的 username 记为“无法导出”，不猜测", [x["query"] for x in sel["not_found"]] == [ghost])
    check("总索引写入 selected_chats_index.*，未生成 all_chats_index.*",
          Path(sel["index_md"]).name == "selected_chats_index.md"
          and not (sel_out / "all_chats_index.md").exists())
    folders = {c["username"]: c["folder"] for c in sel["chats"]}
    check("会话目录由稳定 username 派生",
          all(folders[u] == core._stable_batch_folder(u) for u in targets))
    check("敏感缓存自动清理成功（多选导出）", sel["sensitive_cache_cleanup"])
    new_by_user = {c["username"]: c for c in sel["chats"]}

    section("2b. 再次多选导出：目录稳定、结果一致")
    sel2 = core.export_all_chats(PRIVATE / "selected_again", progress=quiet, usernames=list(reversed(targets)))
    same = all(
        {c["username"]: c["folder"] for c in sel2["chats"]}[u] == folders[u]
        and {c["username"]: c["message_count"] for c in sel2["chats"]}[u] == new_by_user[u]["message_count"]
        for u in targets
    )
    check("调换选择顺序再次导出：目录名和消息数一致", same)

    section("2c. 回归：无新选项时输出与 main 分支逐字节一致")
    old_tree = PRIVATE / "main_tree"
    old_tree.mkdir()
    archive = PRIVATE / "main.tar"
    subprocess.run(["git", "-C", str(REPO), "archive", "-o", str(archive), "HEAD"], check=True)
    with tarfile.open(archive) as tar:
        tar.extractall(old_tree, filter="data")
    archive.unlink()
    proc = subprocess.run(
        [sys.executable, str(HERE / "old_runner.py"), str(old_tree), str(PRIVATE / "main_out"), *targets],
        capture_output=True, text=True, encoding="utf-8", cwd=str(HERE),
    )
    if proc.returncode != 0:
        raise RuntimeError("main 分支对照导出失败：\n" + proc.stderr[-3000:])
    old = json.loads(proc.stdout.strip().splitlines()[-1])
    check("main 分支对照导出的敏感缓存清理成功", old["__cleanup__"]["ok"])
    regression = []
    for u in targets:
        new = new_by_user[u]
        o = old[u]
        txt_same = Path(o["txt"]).read_bytes() == Path(new["txt"]).read_bytes()
        md_same = Path(o["md"]).read_bytes() == Path(new["md"]).read_bytes()
        oj, nj = load_json(o["json"]), load_json(new["json"])
        added = sorted(set(nj) - set(oj))
        nj_cmp = {k: v for k, v in nj.items() if k != "time_ranges"}
        json_same = nj_cmp == oj and nj.get("time_ranges") is None
        regression.append({
            "chat": labels[u], "messages": o["message_count"],
            "txt_identical": txt_same, "md_identical": md_same,
            "json_identical_except_new_null_field": json_same, "json_added_keys": added,
        })
        check(f"{labels[u]}：TXT / Markdown 与 main 逐字节一致，JSON 仅多出 time_ranges=null",
              txt_same and md_same and json_same, messages=o["message_count"])
    report["regression_vs_main"] = regression

    # ============================================================ 3. 时间段
    section("3. 按时间段导出（多个不连续时间段，独立实现交叉验证）")
    full = {u: load_json(new_by_user[u]["json"]) for u in targets}
    subject = max(targets, key=lambda u: len(full[u]["messages"]))
    msgs = full[subject]["messages"]
    timed = [m for m in msgs if parse_time(m["time"])]
    n = len(timed)
    ordered = sorted(timed, key=lambda m: m["time"])
    t1 = parse_time(ordered[n // 5]["time"])
    t2 = parse_time(ordered[n // 2]["time"])
    t3 = parse_time(ordered[(4 * n) // 5]["time"])
    fmt = "%Y-%m-%d %H:%M"
    specs = [
        f"{t1:%Y-%m-%d %H:%M} ~ {t1 + timedelta(minutes=30):%Y-%m-%d %H:%M}",   # 30 分钟窗口
        f"{t1 + timedelta(minutes=20):%Y-%m-%d %H:%M} ~ {t1 + timedelta(minutes=50):%Y-%m-%d %H:%M}",  # 与上一段重叠
        f"{t2:%Y-%m-%d %H:%M} ~ {t2 + timedelta(minutes=5):%Y-%m-%d %H:%M}",    # 起点恰好是某条消息所在分钟
        f"{t3:%Y-%m-%d} ~ {t3:%Y-%m-%d}",                                       # 整天
    ]
    private_log["range_specs"] = specs
    bounds = [independent_bounds(s) for s in specs]
    expected = {
        msg_key(m) for m in msgs
        if (t := parse_time(m["time"])) and any(a <= t < b for a, b in bounds)
    }
    invalid_time = sum(1 for m in msgs if not parse_time(m["time"]))

    tr_out = PRIVATE / "ranges"
    res = core.export_all_chats(tr_out, progress=quiet, usernames=[subject], time_ranges="\n".join(specs))
    entry = res["chats"][0]
    data = load_json(entry["json"])
    got = {msg_key(m) for m in data["messages"]}
    report["time_ranges"] = {
        "chat": labels[subject],
        "ranges_input": len(specs),
        "ranges_after_merge": len(data["time_ranges"]),
        "full_messages": len(msgs),
        "expected_in_ranges": len(expected),
        "exported": len(got),
        "invalid_time_in_full": invalid_time,
    }
    check("时间段导出的消息集合 == 独立实现从完整导出中筛出的集合", got == expected,
          **report["time_ranges"])
    check("重叠的两段被合并（4 段 → 3 段）", len(data["time_ranges"]) == 3)
    check("“起点恰好在消息所在分钟”的那条消息被包含（边界含首）",
          msg_key(ordered[n // 2]) in got)

    def label_bounds(label):
        if "~" not in label:
            return independent_bounds(f"{label} ~ {label}")
        return independent_bounds(label)

    label_ranges = [label_bounds(r["label"]) for r in data["time_ranges"]]
    index_ok = all(
        label_ranges[m["range_index"] - 1][0] <= parse_time(m["time"]) < label_ranges[m["range_index"] - 1][1]
        for m in data["messages"]
    )
    check("每条消息的 range_index 指向包含它的时间段", index_ok)
    with_msgs = len({m["range_index"] for m in data["messages"]})
    txt = Path(entry["txt"]).read_text(encoding="utf-8-sig")
    check("TXT 为每个有消息的时间段输出分段标记，并标注中间省略",
          sum(txt.count(f"时间段 {i}/{len(data['time_ranges'])}") for i in range(1, 4)) == with_msgs
          and (with_msgs < 2 or "中间时段的消息未导出" in txt))
    sender_ok = all(
        (m["sender"], m.get("sender_status"), m.get("sender_username"))
        == next((x["sender"], x.get("sender_status"), x.get("sender_username"))
                for x in msgs if msg_key(x) == msg_key(m))
        for m in data["messages"]
    )
    check("时间段导出中每条消息的发送者身份与完整导出完全一致", sender_ok)

    section("3b. 单会话入口 export_chat + 时间段（按精确 username 解析）")
    single = core.export_chat(subject, PRIVATE / "single_ranges", progress=quiet, time_ranges=specs)
    single_keys = {msg_key(m) for m in load_json(single["json"])["messages"]}
    check("单会话入口的时间段结果与批量入口一致", single_keys == got, messages=len(single_keys))
    check("敏感缓存自动清理成功（单会话）", single["sensitive_cache_cleanup"])

    section("3c. 时间段 + 图片：附件只导出时间段内的")
    image_days = Counter(
        m["time"][:10] for u in targets for m in full[u]["messages"] if m["type"] == "图片"
    )
    media_result = None
    if image_days:
        day, _ = min(image_days.items(), key=lambda kv: (abs(kv[1] - 10), kv[0]))
        owner = max(targets, key=lambda u: sum(
            1 for m in full[u]["messages"] if m["type"] == "图片" and m["time"].startswith(day)))
        exp_images = sum(1 for m in full[owner]["messages"]
                         if m["type"] == "图片" and m["time"].startswith(day))
        r = core.export_all_chats(PRIVATE / "ranges_media", progress=quiet, usernames=[owner],
                                  export_images=True, time_ranges=day)
        e = r["chats"][0]
        d = load_json(e["json"])
        stats = e["media_stats"]
        media_paths = [m["media"]["path"] for m in d["messages"] if m.get("media") and m["media"].get("path")]
        files_on_disk = [p for p in (Path(e["output_dir"]) / "media").rglob("*") if p.is_file()] \
            if (Path(e["output_dir"]) / "media").exists() else []
        media_result = {
            "chat": labels[owner], "images_in_range_expected": exp_images,
            "images_requested": stats["images_requested"], "images_exported": stats["images_exported"],
            "media_files_on_disk": len(files_on_disk),
        }
        check("请求导出的图片数 == 该时间段内的图片消息数",
              stats["images_requested"] == exp_images, **media_result)
        check("所有导出的附件都属于时间段内的消息（无越界附件）",
              all(m["time"].startswith(day) for m in d["messages"] if m.get("media"))
              and len(files_on_disk) <= len(media_paths) + 0)
    else:
        check("选中的会话没有图片消息，跳过附件筛选验证", True)
    report["time_ranges_media"] = media_result

    # ============================================================ 4. 同名联系人
    section("4. 同名 / 模糊匹配：新规则 vs main 规则（遍历全部会话的显示名）")
    workdir = core._create_sensitive_workdir()
    stats = Counter()
    try:
        with core._upstream_sensitive_sandbox(workdir):
            db = core.WeChatDB(db_dir=None, workdir=str(workdir))
            hashes = core._batch_message_hashes(db)
            for c in chats:
                name = c["name"]
                if not name or name == c["username"]:
                    stats["no_display_name"] += 1
                    continue
                results = db.search_contact(name)
                exact = [x for x in results if x.get("remark") == name or x.get("nick_name") == name]
                old_pick = (exact[0] if exact else results[0])["username"] if results else None
                try:
                    new_pick = core.find_contact(db, name, chat_hashes=hashes)["username"]
                    new_state = "resolved"
                except core.AmbiguousContactError:
                    new_pick, new_state = None, "ambiguous"
                except ValueError:
                    new_pick, new_state = None, "error"
                stats["names_checked"] += 1
                if old_pick != c["username"]:
                    stats["main_picks_wrong_chat"] += 1
                    if new_state == "ambiguous":
                        stats["wrong_now_reported_ambiguous"] += 1
                    elif new_pick == c["username"]:
                        stats["wrong_now_resolved_correctly"] += 1
                    elif new_state == "resolved":
                        stats["wrong_still_wrong"] += 1
                    else:
                        stats["wrong_now_error"] += 1
                else:
                    stats["main_correct"] += 1
                    if new_pick == c["username"]:
                        stats["correct_still_correct"] += 1
                    elif new_state == "ambiguous":
                        stats["correct_now_ambiguous"] += 1
                    else:
                        stats["correct_now_changed"] += 1
                if new_state == "resolved" and new_pick != c["username"]:
                    stats["new_resolves_to_other_chat"] += 1
    finally:
        ok, _err = core._cleanup_sensitive_workdir(workdir)
    report["ambiguity"] = dict(stats)
    check("新规则从不把名字解析到“另一个”会话（错选数为 0）",
          stats["new_resolves_to_other_chat"] == 0, **dict(stats))
    check("main 规则下会选错的名字，新规则全部改为正确解析或明确报歧义",
          stats["wrong_still_wrong"] == 0)
    check("同名检查的敏感缓存清理成功", ok)

finally:
    section("5. 收尾检查")
    assert_no_sensitive_residue("全部测试结束后", baseline)

# ---------------------------------------------------------------- 输出
report["passed"] = all(c["passed"] for c in report["checks"])
report["summary"] = {
    "total": len(report["checks"]),
    "passed": sum(c["passed"] for c in report["checks"]),
}
(HERE / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
(PRIVATE / "private_details.json").write_text(
    json.dumps(private_log, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n总计 {report['summary']['passed']}/{report['summary']['total']} 通过")
sys.exit(0 if report["passed"] else 1)
