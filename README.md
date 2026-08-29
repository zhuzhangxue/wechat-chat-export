[README-v1.1.1.md](https://github.com/user-attachments/files/31588394/README-v1.1.1.md)
# 微信聊天导出给大模型
**WeChat Chat Export for LLM**

将 Windows 微信 4.x 的私聊与群聊记录，本地整理并导出为适合 GPT、Claude、Gemini 等大模型读取的 TXT / JSON。

> 目标不是做完整微信备份，而是把聊天记录转换成更适合 LLM 阅读、总结、检索和分析的结构化文本。

---

## 使用前必读

> ⚠️ **使用前请先启动并登录 Windows 微信，并保持微信在后台运行。**

程序在点击“开始导出”时会自动检测 Windows 微信是否正在运行。

如果没有检测到微信，会提示：

```text
未检测到正在运行的 Windows 微信。

请先启动并登录微信，保持微信在后台运行，然后重新开始导出。
```

导出流程在本地完成；本项目代码不包含把聊天记录上传到服务器的逻辑。

聊天记录、数据库密钥和解密缓存都属于敏感数据，请妥善保管导出文件。

---

## 当前功能

- GUI 图形界面，普通用户无需操作 CMD
- 输入好友备注名、昵称或群名即可导出
- 自动识别私聊 / 群聊
- 群聊尽量按成员区分发送者
- 保留普通文本
- 尝试恢复 ZSTD 压缩的长文本
- 解析微信引用回复（`appmsg type=57`）
- 简化撤回等系统 XML 消息
- 图片 / 语音 / 视频 / 动画表情保留为占位符
- 文件 / 链接 / 卡片尽量保留标题或描述
- 每个会话保存到独立目录，避免互相覆盖
- 同时输出 LLM 友好 TXT 与结构化 JSON
- Windows EXE 使用自定义应用图标

---

## 输出示例

```text
========== 2026-08-29 ==========

2026-08-29 10:21:03 | 张三：下午几点集合？
2026-08-29 10:21:18 | 李四：三点吧
2026-08-29 10:21:26 | 我：可以
2026-08-29 10:22:01 | 王五：[图片]
2026-08-29 10:23:14 | 李四：我觉得改成三点半更好
    ↳ 引用 张三：下午几点集合？

2026-08-29 10:30:42 | 张三：[撤回] “张三”撤回了一条消息
```

导出目录：

```text
exports/
└─ 会话名/
   ├─ chat_full_for_llm.txt
   └─ chat_full_parsed.json
```

### TXT

适合直接上传给 GPT、Claude、Gemini 等大模型进行：

- 聊天总结
- 时间线整理
- 对话分析
- 关系 / 沟通模式分析
- 信息检索
- 长期聊天记录归纳

### JSON

保留更完整的结构化字段，方便二次开发、脚本处理或数据分析。

---

## 普通用户使用方法

### 1. 启动微信

先启动并登录 **Windows 微信客户端**，然后保持微信在后台运行。

### 2. 下载程序

正式版本建议从 GitHub **Releases** 下载：

```text
WeChat-Chat-Export-for-LLM.exe
```

如果当前还没有 Release，也可以在：

```text
Actions
→ Build Windows EXE
→ 最新一次成功的构建
→ Artifacts
→ WeChat-Chat-Export-for-LLM-Windows
```

下载最新测试版本。

### 3. 开始导出

运行 EXE 后：

1. 输入好友的准确备注名、昵称或群聊名称
2. 根据需要选择输出目录
3. 点击“开始导出”
4. 等待程序读取并解析聊天记录
5. 完成后点击“打开导出文件夹”

---

## Windows SmartScreen 提示

目前 EXE 尚未使用可信代码签名证书。

因此 Windows 可能显示：

```text
Windows 已保护你的电脑
Microsoft Defender SmartScreen 阻止了无法识别的应用启动
```

这类提示表示 Windows 暂时无法验证该新应用的发布者 / 信誉，**不等同于 Defender 已检测到病毒**。

本项目源码、构建流程和 GitHub Actions 均公开可见。

后续计划为正式发布版本增加可信代码签名。

---

## 私聊与群聊

### 私聊

私聊通常输出为：

```text
时间 | 我：消息
时间 | 对方：消息
```

### 群聊

微信 4.x 的群消息发送者信息比私聊复杂。

部分群文本消息会在 `message_content` 中以类似：

```text
wxid_xxxxx: 正文
```

的形式保存真实发送者，而 `real_sender_id` 并不总是足够可靠。

本项目在群聊模式下会优先尝试：

```text
消息中的成员 wxid
→ 联系人 / 昵称映射
→ 底层 sender 信息
→ 无法识别时使用成员占位符
```

因此群聊可以按成员导出，但极少数特殊消息仍可能无法还原完整成员昵称。

---

## 消息类型处理

| 微信消息 | 当前导出结果 |
|---|---|
| 普通文字 | 保留正文 |
| 长文本 | 尝试解压并恢复正文 |
| 引用回复 | 回复正文 + 被引用内容 |
| 图片 | `[图片]` |
| 语音 | `[语音]` |
| 视频 | `[视频]` |
| 动画表情 | `[动画表情]` |
| 位置 | `[位置]` |
| 文件 | 尽量保留文件名 |
| 链接 / 卡片 | 尽量保留标题 / 描述 |
| 撤回消息 | 简化为 `[撤回] ...` |
| 其他系统消息 | 尽量转换为可读文本 |

---

## 已知限制

- 当前主要导出**聊天文本与消息语义**，不是完整媒体备份工具
- 图片、语音、视频和表情目前不会把媒体文件本体嵌入 TXT / JSON
- 少量特殊微信卡片可能只能显示为占位符
- 同名联系人 / 群聊可能产生匹配歧义，建议使用准确备注名或群名
- 群聊中的极少数消息可能无法解析真实成员昵称
- 微信客户端升级后，数据库结构或密钥机制可能变化，需要同步适配

---

## 与 `wechatauto-replica` 的关系

本项目不是重新实现微信数据库解密。

底层依赖：

- `fanyuantaier/wechatauto-replica`
- Apache License 2.0

当前构建固定使用上游提交：

```text
04ef8cbde3862cff90b5f6b42c9ebfcea44ef48d
```

上游负责：

```text
微信本地数据库定位 / 解密
→ 联系人与消息读取
→ 底层微信 4.x 数据访问
```

本项目在其上增加：

```text
微信聊天数据
→ 长文本 / ZSTD 恢复
→ 引用回复解析
→ 撤回 / 系统消息清洗
→ 群成员识别
→ LLM 友好格式整理
→ TXT / JSON 导出
→ GUI 与 Windows EXE
```

---

## 从源码运行

环境建议：

```text
Windows 10 / 11
Python 3.12
Windows 微信 4.x
```

安装依赖：

```powershell
python -m pip install zstandard
python -m pip install "https://github.com/fanyuantaier/wechatauto-replica/archive/04ef8cbde3862cff90b5f6b42c9ebfcea44ef48d.zip"
```

启动 GUI：

```powershell
python app.py
```

CLI：

```powershell
python cli.py "好友备注名或群名"
```

---

## GitHub Actions 自动构建 Windows EXE

仓库包含：

```text
.github/workflows/build-windows.yml
```

修改以下核心文件并提交到 `main` 后会自动触发 Windows 构建：

```text
app.py
cli.py
exporter_core.py
requirements.txt
assets/app.ico
build-windows.yml
```

也可以在 GitHub：

```text
Actions
→ Build Windows EXE
→ Run workflow
```

手动构建。

构建成功后会生成：

```text
WeChat-Chat-Export-for-LLM-Windows
```

Artifact，其中包含 Windows EXE / ZIP 构建产物。

---

## 隐私与安全

**不要把自己的聊天记录或微信数据库提交到 GitHub。**

仓库的 `.gitignore` 已默认排除：

```text
exports/
final_export/
**/keys.json
wechatauto_db/
*.sqlite
*.sqlite3
build/
dist/
*.spec
```

提交代码前仍建议检查：

```bash
git status
```

确认没有包含：

- 私人聊天 TXT / JSON
- 微信 wxid
- `keys.json`
- 解密数据库
- 本地缓存
- 个人测试数据

---

## 项目定位

本项目适合：

> 需要将自己本地的微信聊天历史整理成可供大模型读取、总结或分析的数据文件的 Windows 用户。

它不是：

- 微信云备份服务
- 微信服务器抓取工具
- 完整媒体归档工具
- 微信官方产品

---

## License

本项目使用 **Apache License 2.0**。

第三方依赖及授权信息见：

```text
THIRD_PARTY_NOTICES.md
```

---

## Disclaimer

本项目仅用于处理用户本人有权访问的本地微信数据。

请遵守当地法律法规、微信相关服务条款以及聊天参与者的隐私权，不要未经授权导出、传播或公开他人的敏感聊天内容。
