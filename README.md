# 微信聊天导出给大模型
**WeChat Chat Export for LLM**

把 Windows 微信私聊或群聊导出成适合 GPT、Claude、Gemini 等大模型读取的 TXT / JSON。

## 当前功能

- GUI 图形界面，不再要求普通用户操作 CMD
- 输入好友备注/昵称或群名即可导出
- 自动识别私聊 / 群聊
- 群聊按成员区分发送者
- 普通文本、ZSTD 长文本
- 引用回复 `appmsg type=57`
- 撤回等系统 XML 简化
- 图片 / 语音 / 视频 / 表情保留占位符
- 文件 / 链接 / 卡片尽量保留标题
- 每个会话独立输出目录

输出：

```text
exports/
└─ 会话名/
   ├─ chat_full_for_llm.txt
   └─ chat_full_parsed.json
```

## 群聊说明

底层 `wechatauto-replica` 本身能够读取群聊数据库。

微信 4.x 的群聊有一个额外问题：群文本消息的真实发送者经常写在 `message_content` 前缀里，例如：

```text
wxid_xxxxx: 正文
```

而 `real_sender_id` 并不总是可靠。

本项目在群聊模式下优先解析这个前缀，再映射成员昵称；无法解析时才回退到底层 sender 信息。

因此 **v1.1.0 开始正式支持群聊导出**。

## GitHub Actions 构建 Windows EXE

仓库包含：

```text
.github/workflows/build-windows.yml
```

创建类似：

```text
v1.1.0
```

的 tag 并 push 后，GitHub Actions 会在 Windows runner 上构建：

```text
WeChat-Chat-Export-for-LLM.exe
```

也可以在 Actions 页面手动运行 workflow。

> 注意：未做可信代码签名的新 EXE 仍可能被 Windows SmartScreen 提示。GUI EXE 能改善使用体验，但不能替代正式代码签名。

## 本地源码运行

Python 3.12：

```powershell
pip install zstandard
pip install "https://github.com/fanyuantaier/wechatauto-replica/archive/04ef8cbde3862cff90b5f6b42c9ebfcea44ef48d.zip"
python app.py
```

保持 Windows 微信处于登录状态。

## 隐私

不要把以下内容提交到 GitHub：

- `exports/`
- `keys.json`
- 解密 SQLite
- 微信 wxid
- 私人聊天记录

`.gitignore` 已默认忽略主要敏感目录，但发布前仍应检查：

```bash
git status
```

## 上游

底层依赖：

- `fanyuantaier/wechatauto-replica`
- 固定提交：`04ef8cbde3862cff90b5f6b42c9ebfcea44ef48d`
- Apache License 2.0
