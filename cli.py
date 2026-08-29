# -*- coding: utf-8 -*-
import argparse

from exporter_core import export_chat


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="微信聊天信息导出给大模型")
    p.add_argument("name", help="好友备注/昵称或群名")
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
    p.add_argument(
        "--media",
        action="store_true",
        help="等同于同时开启 --images 和 --files",
    )
    a = p.parse_args()

    result = export_chat(
        a.name,
        a.out,
        progress=print,
        export_images=(a.images or a.media),
        export_files=(a.files or a.media),
    )
    print(result)
