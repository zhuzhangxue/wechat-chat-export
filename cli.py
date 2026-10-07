# -*- coding: utf-8 -*-
import argparse

from exporter_core import (
    clear_sensitive_cache,
    export_all_chats,
    export_chat,
    install_local_asr_model,
    install_rust_silk,
)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="微信聊天信息导出给大模型")
    p.add_argument("name", nargs="?", help="好友备注/昵称或群名")
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
            "导出本机全部私聊和群聊：每个会话一个文件夹，"
            "并在输出目录生成 all_chats_index.json / all_chats_index.md 总索引"
        ),
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="配合 --all 使用：最多导出多少个会话，便于先小范围试跑",
    )
    p.add_argument(
        "--include-empty",
        action="store_true",
        help=(
            "配合 --all 使用：连只加过好友、从未聊过的联系人也逐个尝试"
            "（默认跳过，因为它们不会产生任何导出内容）"
        ),
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
    a = p.parse_args()

    if a.limit is not None and a.limit <= 0:
        p.error("--limit 必须是正整数（0 不会被当成“不限量”）。")
    if a.limit is not None and not a.export_all:
        p.error("--limit 只能配合 --all 使用。")
    if a.include_empty and not a.export_all:
        p.error("--include-empty 只能配合 --all 使用。")

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
    if a.export_all:
        if a.name:
            print(f"注意：已指定 --all，忽略会话关键词“{a.name}”。")
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
            include_empty=a.include_empty,
        )
        print(
            f"共发现会话 {result['discovered_total']}"
            f"（私聊 {result['private_total']}，群聊 {result['group_total']}），"
            f"其中有消息记录 {result['with_messages']}；本次处理 {result['total']}。"
        )
        if result.get("skipped_no_messages"):
            print(
                f"另有 {result['skipped_no_messages']} 个从未有消息的会话已跳过"
                "（--include-empty 可一并尝试）。"
            )
        print(
            f"成功 {result['exported']}，无消息跳过 {result['skipped_empty']}，"
            f"失败 {result['failed']}，消息总数 {result['total_messages']}。"
        )
        for item in result["chats"]:
            if item["status"] != "exported":
                print(f"  {item['status']}：{item['name']}（{item['error']}）")
        print("输出目录：" + result["output_dir"])
        print("总索引：" + result["index_md"])
        if not result["sensitive_cache_cleanup"]:
            print(
                "敏感临时缓存自动清理失败："
                + str(result.get("sensitive_cache_cleanup_error"))
            )
            raise SystemExit(1)
        raise SystemExit(1 if result["failed"] else 0)

    if not a.name:
        p.error(
            "请提供好友备注/昵称或群名；"
            "或用 --all 导出全部私聊和群聊；"
            "或使用 --install-asr / --install-rust-silk / "
            "--clear-sensitive-cache"
        )

    result = export_chat(
        a.name,
        a.out,
        progress=print,
        export_images=(a.images or a.media),
        export_files=(a.files or a.media),
        export_voices=(a.voices or a.media or a.transcribe_voices),
        export_videos=(a.videos or a.media),
        transcribe_voices=a.transcribe_voices,
        db_dir=a.db_dir,
    )
    print(result)
