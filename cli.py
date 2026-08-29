# -*- coding: utf-8 -*-
import argparse
from exporter_core import export_chat

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="微信聊天信息导出给大模型")
    p.add_argument("name", help="好友备注/昵称或群名")
    p.add_argument("--out", default="exports")
    a = p.parse_args()
    result = export_chat(a.name, a.out, progress=print)
    print(result)
