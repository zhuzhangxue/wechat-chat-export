# 微信聊天导出给大模型

**WeChat Chat Export for LLM**

把 Windows 微信 4.x 的私聊、群聊整理成 TXT / JSON，方便直接交给 GPT、Claude、Gemini 等大模型读取。

这个项目不做完整微信备份，重点是把聊天内容尽量还原成「人能看、大模型也容易读」的文本。

## 下载

当前版本：**v1.1.2**

- [下载 Windows EXE](https://github.com/zhuzhangxue/wechat-chat-export-for-llm/releases/download/v1.1.2/WeChat-Chat-Export-for-LLM.exe)
- [下载 Windows ZIP](https://github.com/zhuzhangxue/wechat-chat-export-for-llm/releases/download/v1.1.2/WeChat-Chat-Export-for-LLM-Windows.zip)
- [查看 Releases](https://github.com/zhuzhangxue/wechat-chat-export-for-llm/releases)

EXE 是单文件版本，不需要另外安装 Python、Conda 或项目依赖。

> 使用前请先启动并登录 Windows 微信，并保持微信在后台运行。

## 怎么用

1. 启动并登录 Windows 微信。
2. 打开 `WeChat-Chat-Export-for-LLM.exe`。
3. 输入好友的准确备注名、昵称，或者群聊名称。
4. 选择输出目录；不改的话默认写到程序旁边的 `exports`。
5. 点击「开始导出」。
6. 完成后点击右下角「打开导出文件夹」。

程序会在开始导出前检查微信是否正在运行，没有检测到时会直接提示。

不同会话会分别保存：

```text
exports/
├─ 好友 A/
│  ├─ chat_full_for_llm.txt
│  └─ chat_full_parsed.json
└─ 某个群聊/
   ├─ chat_full_for_llm.txt
   └─ chat_full_parsed.json
```

其中：

- `chat_full_for_llm.txt`：适合直接上传给大模型。
- `chat_full_parsed.json`：保留更多结构化字段，适合脚本处理或二次开发。

## 导出效果

TXT 会按日期、时间和发送者整理：

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

## 目前能处理哪些消息

| 消息类型 | 导出结果 |
| --- | --- |
| 普通文字 | 保留正文 |
| 较长文字 / 压缩文本 | 尝试解压后恢复正文 |
| 引用回复 | 保留回复正文和被引用内容 |
| 图片 | `[图片]` |
| 语音 | `[语音]` |
| 视频 | `[视频]` |
| 动画表情 | `[动画表情]` |
| 位置 | `[位置]` |
| 文件 | 尽量保留文件名 |
| 链接 / 卡片 | 尽量保留标题或描述 |
| 撤回消息 | 简化成可读的 `[撤回] ...` |
| 其他系统消息 | 尽量去掉原始 XML，只留下可读内容 |

微信内部的消息类型很多，少数特殊卡片仍可能只能显示成占位符。

图片、语音、视频等目前只保留「这里曾经有一条什么类型的消息」，不会把媒体文件本体导出来。

## 群聊

群聊和私聊最大的区别之一，是发送者信息不总在同一个字段里。

微信 4.x 的部分群消息会把真实发送者写在正文前面，例如：

```text
wxid_xxxxx: 正文
```

程序会优先从这里识别成员，再结合联系人昵称和底层 sender 信息补充。

如果都无法还原，才会显示类似：

```text
成员#123
```

所以群聊可以导出，但极少数消息的成员昵称仍可能识别不完整。

## 为什么要单独做这个项目

底层数据库读取和解密由 [`fanyuantaier/wechatauto-replica`](https://github.com/fanyuantaier/wechatauto-replica) 完成。

这个项目没有重新实现微信数据库解密，主要处理的是「读出来以后怎么整理给大模型」的问题。

实际聊天数据库里，一些看起来是普通文字的内容并不直接以普通文字保存。例如：

- 长文本可能经过 Zstandard 压缩；
- 引用回复位于 `appmsg` 结构中，常见 `type=57`；
- 撤回消息可能直接是一段 XML；
- 群聊发送者有时要从消息正文前缀里还原。

如果只按最外层消息类型导出，最后很容易得到一堆：

```text
[文本]
[文件/链接/卡片]
```

真正有用的聊天内容反而丢了。

本项目主要补的就是这一层解析和整理。

当前构建固定使用上游提交：

```text
04ef8cbde3862cff90b5f6b42c9ebfcea44ef48d
```

上游使用 Apache License 2.0，相关说明见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。

## Windows SmartScreen

当前发布的 EXE 还没有可信代码签名证书。

因此第一次下载运行时，Windows SmartScreen 可能显示「Windows 已保护你的电脑」或「无法识别的应用」。

这是因为 Windows 暂时无法验证这个新程序的发布者和应用信誉，不等同于已经检测到病毒。

项目源码和 GitHub Actions 构建流程都公开在仓库里。如果你不愿意运行未签名的 EXE，可以直接查看源码并自行构建。

**不建议为了运行本工具关闭 Microsoft Defender、关闭 SmartScreen，或给整个目录添加安全软件排除项。**

## 为什么 EXE 有 70 多 MB

Windows 版使用 PyInstaller 打成单文件 EXE。

为了让普通用户不需要另外安装 Python 和依赖，Python 运行时、微信数据读取相关依赖等都会一起打进程序，所以文件体积会明显大于源码本身。

`--onefile` 模式启动时还需要先解包运行环境，因此第一次打开可能会比普通原生小工具慢几秒，这是正常现象。

## 从源码运行

推荐环境：

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

也可以使用命令行：

```powershell
python cli.py "好友备注名或群名"
```

## Windows EXE 怎么构建

仓库里的：

```text
.github/workflows/build-windows.yml
```

会通过 GitHub Actions 在 Windows 环境中自动打包 EXE。

修改这些文件并提交到 `main` 后会触发新构建：

```text
app.py
cli.py
exporter_core.py
requirements.txt
assets/app.ico
.github/workflows/build-windows.yml
```

也可以在 GitHub 的 Actions 页面手动运行 `Build Windows EXE`。

当前 GUI 和 EXE 使用同一套应用图标。

## 隐私

聊天记录本身就是敏感数据。

导出文件只写到你选择的本地目录，本项目没有提供把聊天内容上传到远端的功能。

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

不过 `.gitignore` 不是保险箱。提交代码前仍建议看一眼：

```bash
git status
```

确认没有把自己的聊天 TXT / JSON、wxid、数据库、`keys.json` 或其他个人数据带进提交。

## 已知限制

目前比较明确的限制有：

- 只支持 Windows；
- 当前主要面向 Windows 微信 4.x；
- 不导出图片、语音、视频等媒体文件本体；
- 同名联系人或同名群聊可能产生匹配歧义；
- 少数特殊消息类型仍可能解析不完整；
- 群成员昵称只能尽量还原；
- 微信版本更新后，数据库结构或密钥机制变化可能导致现有版本失效。

如果遇到某类消息长期显示成占位符，可以附上**脱敏后的消息类型和结构**提 Issue。

请不要直接上传真实聊天数据库、密钥或私人聊天内容。

## 免责声明

本项目是独立的开源工具，与腾讯、微信（WeChat / Weixin）及其关联公司没有隶属、授权、认可或合作关系。

微信、WeChat、Weixin 及相关名称、商标归其各自权利人所有。

本项目仅用于处理使用者本人有权访问的本地数据。使用者应自行确认其对相关数据拥有合法的访问和处理权限，并遵守所在地法律法规、相关软件服务条款以及聊天参与者的隐私权。

请勿使用本项目访问、导出、分析或传播自己无权处理的数据。

软件按「现状」提供。微信客户端升级、系统环境变化或上游依赖调整，都可能导致功能失效、兼容性变化或导出结果不完整。使用前请自行备份重要数据。

## License

Apache License 2.0。

第三方依赖和许可信息见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。
