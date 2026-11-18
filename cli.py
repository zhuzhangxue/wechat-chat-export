# -*- coding: utf-8 -*-
import argparse

from exporter_core import (
    clear_sensitive_cache,
    export_all_chats,
    export_chat,
    install_local_asr_model,
    install_rust_silk,
    list_chats,
)
from time_ranges import parse_time_ranges


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="微信聊天信息导出给大模型")
    p.add_argument(
        "names",
        nargs="*",
        metavar="name",
        help="好友备注/昵称或群名；写多个即一次导出多个聊天（多选导出）",
    )
    p.add_argument("--out", default="exports")
    p.add_argument(
        "--images",
        action="store_true",
        help="同时导出本机仍有缓存的聊天图片",
    )
    p.add_argument(
        "--files",
        action="store_true",
        help="同时导出本机仍有缓存的聊天文件",
    )
    p.add_argument("--voices", action="store_true", help="同时导出语音；有解码器时生成 WAV")
    p.add_argument("--videos", action="store_true", help="同时导出本机仍有缓存的视频")
    p.add_argument(
        "--transcribe-voices",
        action="store_true",
        help="用本地 SenseVoice 将导出的语音转成文字；会自动开启语音导出",
    )
    p.add_argument(
        "--media",
        action="store_true",
        help="同时开启图片、文件、语音和视频导出",
    )
    p.add_argument(
        "--all",
        dest="export_all",
        action="store_true",
        help=(
            "导出本机所有能够从本地消息表可靠识别的私聊和群聊，"
            "并生成 all_chats_index.json / all_chats_index.md 总索引"
        ),
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="配合 --all 使用：只导出最近的 N 个会话，便于先小范围试跑",
    )
    p.add_argument(
        "--install-asr",
        action="store_true",
        help="下载安装本地 SenseVoice 语音识别模型后退出",
    )
    p.add_argument(
        "--install-rust-silk",
        action="store_true",
        help="下载安装 rust-silk 语音解码器后退出",
    )
    p.add_argument(
        "--clear-sensitive-cache",
        action="store_true",
        help=(
            "清除当前版本临时敏感缓存，以及 v1.3.3 及更早版本 / "
            "wechatauto-replica 默认留下的密钥和解密数据库缓存后退出"
        ),
    )
    p.add_argument(
        "--db-dir",
        default=None,
        help=(
            "微信数据目录（微信「设置 → 文件管理」里显示的那个）。"
            "默认自动探测；数据目录被自行迁移过、或自动探测读到错误副本时指定。"
        ),
    )
    p.add_argument(
        "--chats-file",
        default=None,
        metavar="文件",
        help="UTF-8 文本文件，每行一个要导出的聊天（备注/昵称/群名，# 开头为注释），与命令行里的名字合并",
    )
    p.add_argument(
        "--list-chats",
        action="store_true",
        help="列出本机可导出的私聊和群聊（名称、类型、最近消息时间）后退出",
    )
    p.add_argument(
        "--since",
        default=None,
        metavar="开始",
        help="开始日期/时间（含），如 2025-03-01 或 \"2025-03-01 14:00\"；可单独用或配合 --until",
    )
    p.add_argument(
        "--until",
        default=None,
        metavar="结束",
        help="结束日期/时间（含），如 2025-03-05 或 \"2025-03-05 18:30\"；可单独用或配合 --since",
    )
    p.add_argument(
        "--range",
        dest="ranges",
        action="append",
        default=[],
        metavar="时间段",
        help=(
            "一个时间段，如 \"2025-03-01 14:00 ~ 16:30\"；可重复多次表示多个不连续时间段，"
            "与 --since/--until、--ranges-file 合并使用"
        ),
    )
    p.add_argument(
        "--ranges-file",
        default=None,
        metavar="文件",
        help="UTF-8 文本文件，每行一个时间段（# 开头为注释），适合大量不连续时间段",
    )
    a = p.parse_args()

    names = [n.strip() for n in a.names if n and n.strip()]
    if a.chats_file:
        try:
            with open(a.chats_file, encoding="utf-8-sig") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        names.append(line)
        except OSError as exc:
            p.error(f"无法读取 --chats-file：{exc}")
    names = list(dict.fromkeys(names))

    range_specs = list(a.ranges)
    if a.since or a.until:
        range_specs.append(f"{a.since or ''} ~ {a.until or ''}")
    if a.ranges_file:
        try:
            with open(a.ranges_file, encoding="utf-8-sig") as fh:
                range_specs.append(fh.read())
        except OSError as exc:
            p.error(f"无法读取 --ranges-file：{exc}")
    try:
        time_ranges = parse_time_ranges(range_specs)
    except ValueError as exc:
        p.error(str(exc))
    if time_ranges:
        print(f"导出时间段（合并后共 {len(time_ranges)} 段）：")
        for index, item in enumerate(time_ranges, 1):
            print(f"  {index}. {item.label}")

    if a.limit is not None and a.limit <= 0:
        p.error("--limit 必须是正整数。")
    if a.limit is not None and not a.export_all:
        p.error("--limit 只能配合 --all 使用。")

    if a.install_asr:
        install_local_asr_model(progress=print)
        raise SystemExit(0)
    if a.install_rust_silk:
        install_rust_silk(progress=print)
        raise SystemExit(0)
    if a.clear_sensitive_cache:
        report = clear_sensitive_cache()
        for path in report.get("removed") or []:
            print("已清除：" + path)
        if not report.get("removed"):
            print("没有发现需要清理的敏感缓存。")
        failed = report.get("failed") or []
        if failed:
            for item in failed:
                print(
                    "清理失败："
                    + str(item.get("path"))
                    + "："
                    + str(item.get("error"))
                )
            raise SystemExit(1)
        raise SystemExit(0)
    if a.list_chats:
        listing = list_chats(db_dir=a.db_dir, progress=print)
        for item in listing["chats"]:
            kind = "群聊" if item["is_group"] else "私聊"
            print(f"{kind}\t{item['last_time_text'] or '—'}\t{item['name']}")
        if not listing["sensitive_cache_cleanup"]:
            print("敏感临时缓存自动清理失败：" + str(listing.get("sensitive_cache_cleanup_error")))
            raise SystemExit(1)
        raise SystemExit(0)

    multi = len(names) > 1 and not a.export_all
    if a.export_all or multi:
        if a.export_all and names:
            print(f"注意：已指定 --all，忽略会话关键词：{'、'.join(names)}")
        result = export_all_chats(
            a.out,
            progress=print,
            export_images=(a.images or a.media),
            export_files=(a.files or a.media),
            export_voices=(a.voices or a.media or a.transcribe_voices),
            export_videos=(a.videos or a.media),
            transcribe_voices=a.transcribe_voices,
            db_dir=a.db_dir,
            limit=a.limit,
            time_ranges=time_ranges,
            keywords=names if multi else None,
        )
        print(
            f"可可靠识别会话 {result['discovered_total']}，"
            f"本次处理 {result['selected_total']}；"
            f"成功 {result['exported']}，无消息 {result['skipped_empty']}，"
            f"失败 {result['failed']}，消息总数 {result['total_messages']}。"
        )
        if result.get("unresolved_message_tables"):
            print(
                f"另有 {result['unresolved_message_tables']} 个消息表无法可靠反查身份，"
                "已跳过而不是猜测。"
            )
        for item in result.get("not_found") or []:
            print(f"选中但无法导出：{item['query']}（{item['reason']}）")
        print("输出目录：" + result["output_dir"])
        print("总索引：" + result["index_md"])
        if not result["sensitive_cache_cleanup"]:
            print(
                "敏感临时缓存自动清理失败："
                + str(result.get("sensitive_cache_cleanup_error"))
            )
            raise SystemExit(1)
        raise SystemExit(1 if (result["failed"] or result.get("not_found")) else 0)

    if not names:
        p.error(
            "请提供好友备注/昵称或群名；或用 --all 导出全部聊天；"
            "或使用 --install-asr / --install-rust-silk / "
            "--clear-sensitive-cache"
        )

    result = export_chat(
        names[0],
        a.out,
        progress=print,
        export_images=(a.images or a.media),
        export_files=(a.files or a.media),
        export_voices=(a.voices or a.media or a.transcribe_voices),
        export_videos=(a.videos or a.media),
        transcribe_voices=a.transcribe_voices,
        db_dir=a.db_dir,
        time_ranges=time_ranges,
    )
    print(result)
