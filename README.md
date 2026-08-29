[Uploading README.md…]()
# 微信聊天导出给大模型

**WeChat Chat Export for LLM**

把 Windows 微信 4.x 的私聊或群聊整理成 TXT / JSON，方便交给 GPT、Claude、Gemini 等大模型读取。

这个项目只做一件事：把微信本地聊天记录尽量还原成人能看、大模型也容易读的文本。它不是微信备份工具，也不会把图片、语音、视频完整打包出来。

## 使用前先看

- 仅支持 Windows。
- 运行前先启动并登录 Windows 微信，保持微信在后台运行。
- 当前主要面向微信 4.x。微信更新后如果数据库结构或密钥机制变化，可能需要重新适配。
- 图片、语音、视频、动画表情目前只保留占位符，不导出媒体文件本体。
- 建议只处理自己有权访问的数据，不要公开上传私人聊天记录、数据库或密钥。

程序在开始导出前会检查微信进程。如果没有检测到正在运行的微信，会先提示启动并登录微信。

## 下载和使用

正式版本会放在 GitHub Releases。暂时没有 Release 时，可以在 Actions 里下载最新构建：

```text
Actions
→ Build Windows EXE
→ 打开最新一次绿色成功的构建
→ Artifacts
→ WeChat-Chat-Export-for-LLM-Windows
```

解压后运行：

```text
WeChat-Chat-Export-for-LLM.exe
```

然后：

1. 输入好友的准确备注名、昵称，或者群聊名称。
2. 选择输出目录；不改的话会写到程序旁边的 `exports`。
3. 点击「开始导出」。
4. 完成后可以直接打开导出文件夹。

不同会话会放进不同目录，不会互相覆盖。

```text
exports/
├─ 好友 A/
│  ├─ chat_full_for_llm.txt
│  └─ chat_full_parsed.json
└─ 某个群聊/
   ├─ chat_full_for_llm.txt
   └─ chat_full_parsed.json
```

## 导出来是什么样

TXT 会按日期、时间和发送者排列：

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

TXT 适合直接交给大模型。JSON 会多保留一些结构化字段，适合后续脚本处理。

## 目前能处理哪些消息

| 消息类型 | 导出结果 |
| --- | --- |
| 普通文字 | 保留正文 |
| 较长文字 / 压缩文本 | 尝试解压后恢复正文 |
| 引用回复 | 保留回复正文，并附上被引用内容 |
| 图片 | `[图片]` |
| 语音 | `[语音]` |
| 视频 | `[视频]` |
| 动画表情 | `[动画表情]` |
| 位置 | `[位置]` |
| 文件 | 尽量保留文件名 |
| 链接 / 卡片 | 尽量保留标题或描述 |
| 撤回消息 | 简化为可读的 `[撤回] ...` |
| 其他系统消息 | 尽量去掉原始 XML，只保留可读内容 |

微信内部的消息类型不少，少数特殊卡片仍可能只能显示成占位符。

## 群聊

群聊和私聊的一个区别是：发送者信息不总在同一个字段里。

微信 4.x 的部分群消息会把真实发送者写在消息内容前面，例如：

```text
wxid_xxxxx: 正文
```

程序会先尝试从这里识别成员，再用联系人昵称和底层 sender 信息补充。都取不到时，才会显示类似：

```text
成员#123
```

所以群聊可以导出，但成员昵称的还原并不是所有消息都能保证成功。

## 为什么不是直接用上游导出

底层数据库读取和解密由 [`fanyuantaier/wechatauto-replica`](https://github.com/fanyuantaier/wechatauto-replica) 完成。

这个仓库没有重新实现微信数据库解密，主要补的是「导出给大模型」这一层。实际使用中，一些微信消息不能只看最外层类型：

- 长文本可能以 Zstandard 压缩后的二进制形式保存；
- 引用回复会落在 `appmsg` 结构里，`type=57`；
- 撤回等系统消息可能直接是一段 XML；
- 群聊发送者有时需要从消息正文前缀还原。

如果直接把这些内容统一写成 `[文本]`、`[文件/链接/卡片]`，给大模型分析时会丢掉不少真正有用的信息。本项目主要处理的就是这些情况。

当前构建固定使用上游提交：

```text
04ef8cbde3862cff90b5f6b42c9ebfcea44ef48d
```

上游许可证为 Apache License 2.0，详细说明见 `THIRD_PARTY_NOTICES.md`。

## 从源码运行

需要：

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

启动图形界面：

```powershell
python app.py
```

也可以直接用命令行：

```powershell
python cli.py "好友备注名或群名"
```

## Windows EXE 构建

仓库里的：

```text
.github/workflows/build-windows.yml
```

会通过 GitHub Actions 在 Windows 环境中打包 EXE。

修改 `app.py`、`cli.py`、`exporter_core.py`、`requirements.txt`、`assets/app.ico` 或构建配置后提交到 `main`，都会触发新的构建。也可以在 Actions 页面手动运行。

当前 EXE 还没有可信代码签名。Windows SmartScreen 因此可能显示「Windows 已保护你的电脑」或「无法识别的应用」。这是发布者 / 应用信誉提示，不代表项目已经被 Defender 判定为恶意软件。

## 隐私

聊天记录本身就属于敏感数据。导出文件默认只写到本地选择的目录，本项目也没有提供把聊天内容上传到远端的功能。

仓库的 `.gitignore` 已排除常见的敏感文件和构建产物：

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

但 `.gitignore` 不是保险箱。提交代码前仍建议看一眼：

```bash
git status
```

确认没有把自己的聊天 TXT / JSON、wxid、数据库、`keys.json` 或其他个人数据带进提交。

## 已知限制

目前没有计划把它做成完整的微信归档工具。几个比较明确的限制是：

- 不导出图片、语音、视频等媒体本体；
- 同名联系人或同名群聊可能产生匹配歧义；
- 少数特殊消息类型仍可能解析不完整；
- 群成员昵称只能尽量还原；
- 微信版本更新可能让现有读取方式失效；
- 当前只验证 Windows 场景。

如果遇到某一类消息长期显示成占位符，欢迎附上脱敏后的消息类型和结构提 Issue。不要直接上传真实聊天数据库。

## 免责声明

本项目是独立的开源工具，与腾讯、微信（WeChat / Weixin）及其关联公司没有隶属、授权、认可或合作关系。微信、WeChat、Weixin 及相关名称和商标归其各自权利人所有。

本项目仅用于处理使用者本人有权访问的本地数据。请遵守所在地法律法规、相关软件服务条款，并尊重聊天参与者的隐私。不要用它访问、导出或传播自己无权处理的数据。

软件按现状提供。微信客户端升级、系统环境变化或上游依赖调整，都可能导致功能失效或导出结果不完整。使用前请自行备份重要数据。

## License

Apache License 2.0。

第三方依赖和许可信息见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。
