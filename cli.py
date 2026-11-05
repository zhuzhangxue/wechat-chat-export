# -*- coding: utf-8 -*-
import argparse
import sys

from i18n import set_language_session, tr
from exporter_core import (
    clear_sensitive_cache,
    export_all_chats,
    export_chat,
    install_local_asr_model,
    install_rust_silk,
)


if __name__ == "__main__":
    # --lang affects help text, so apply it before building the parser.
    for i, arg in enumerate(sys.argv[1:], start=1):
        if arg == "--lang":
            if i + 1 < len(sys.argv):
                set_language_session(sys.argv[i + 1])
            break
        if arg.startswith("--lang="):
            set_language_session(arg.split("=", 1)[1])
            break

    p = argparse.ArgumentParser(description=tr("微信聊天信息导出给大模型"))
    p.add_argument("name", nargs="?", help=tr("好友备注/昵称或群名"))
    p.add_argument("--out", default="exports")
    p.add_argument(
        "--images",
        action="store_true",
        help=tr("同时导出本机仍有缓存的聊天图片"),
    )
    p.add_argument(
        "--files",
        action="store_true",
        help=tr("同时导出本机仍有缓存的聊天文件"),
    )
    p.add_argument("--voices", action="store_true", help=tr("同时导出语音；有解码器时生成 WAV"))
    p.add_argument("--videos", action="store_true", help=tr("同时导出本机仍有缓存的视频"))
    p.add_argument(
        "--transcribe-voices",
        action="store_true",
        help=tr("用本地 SenseVoice 将导出的语音转成文字；会自动开启语音导出"),
    )
    p.add_argument(
        "--media",
        action="store_true",
        help=tr("同时开启图片、文件、语音和视频导出"),
    )
    p.add_argument(
        "--all",
        dest="export_all",
        action="store_true",
        help=tr(
            "导出本机所有能够从本地消息表可靠识别的私聊和群聊，"
            "并生成 all_chats_index.json / all_chats_index.md 总索引"
        ),
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help=tr("配合 --all 使用：只导出最近的 N 个会话，便于先小范围试跑"),
    )
    p.add_argument(
        "--install-asr",
        action="store_true",
        help=tr("下载安装本地 SenseVoice 语音识别模型后退出"),
    )
    p.add_argument(
        "--install-rust-silk",
        action="store_true",
        help=tr("下载安装 rust-silk 语音解码器后退出"),
    )
    p.add_argument(
        "--clear-sensitive-cache",
        action="store_true",
        help=tr(
            "清除当前版本临时敏感缓存，以及 v1.3.3 及更早版本 / "
            "wechatauto-replica 默认留下的密钥和解密数据库缓存后退出"
        ),
    )
    p.add_argument(
        "--db-dir",
        default=None,
        help=tr(
            "微信数据目录（微信「设置 → 文件管理」里显示的那个）。"
            "默认自动探测；数据目录被自行迁移过、或自动探测读到错误副本时指定。"
        ),
    )
    p.add_argument(
        "--lang",
        choices=["zh", "ru"],
        default=None,
        help=tr("界面语言（zh/ru），仅影响当前运行，不保存到文件"),
    )
    a = p.parse_args()

    if a.limit is not None and a.limit <= 0:
        p.error(tr("--limit 必须是正整数。"))
    if a.limit is not None and not a.export_all:
        p.error(tr("--limit 只能配合 --all 使用。"))

    if a.install_asr:
        install_local_asr_model(progress=print)
        raise SystemExit(0)
    if a.install_rust_silk:
        install_rust_silk(progress=print)
        raise SystemExit(0)
    if a.clear_sensitive_cache:
        report = clear_sensitive_cache()
        for path in report.get("removed") or []:
            print(tr("已清除：{path}", path=path))
        if not report.get("removed"):
            print(tr("没有发现需要清理的敏感缓存。"))
        failed = report.get("failed") or []
        if failed:
            for item in failed:
                print(
                    tr(
                        "清理失败：{path}：{error}",
                        path=str(item.get("path")),
                        error=str(item.get("error")),
                    )
                )
            raise SystemExit(1)
        raise SystemExit(0)
    if a.export_all:
        if a.name:
            print(tr("注意：已指定 --all，忽略会话关键词“{name}”。", name=a.name))
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
        )
        print(
            tr(
                "可可靠识别会话 {discovered_total}，本次处理 {selected_total}；"
                "成功 {exported}，无消息 {skipped_empty}，失败 {failed}，消息总数 {total_messages}。",
                discovered_total=result['discovered_total'],
                selected_total=result['selected_total'],
                exported=result['exported'],
                skipped_empty=result['skipped_empty'],
                failed=result['failed'],
                total_messages=result['total_messages'],
            )
        )
        if result.get("unresolved_message_tables"):
            print(
                tr(
                    "另有 {count} 个消息表无法可靠反查身份，已跳过而不是猜测。",
                    count=result['unresolved_message_tables'],
                )
            )
        print(tr("输出目录：{path}", path=result["output_dir"]))
        print(tr("总索引：{path}", path=result["index_md"]))
        if not result["sensitive_cache_cleanup"]:
            print(
                tr(
                    "敏感临时缓存自动清理失败：{error}",
                    error=str(result.get("sensitive_cache_cleanup_error")),
                )
            )
            raise SystemExit(1)
        raise SystemExit(1 if result["failed"] else 0)

    if not a.name:
        p.error(
            tr(
                "请提供好友备注/昵称或群名；或用 --all 导出全部聊天；"
                "或使用 --install-asr / --install-rust-silk / "
                "--clear-sensitive-cache"
            )
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
