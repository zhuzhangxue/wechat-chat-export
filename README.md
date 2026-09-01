# 微信聊天记录导出

把 Windows 微信 4.1.12+ 的聊天记录导出为 TXT、Markdown 和 JSON，方便交给 GPT、Claude、Gemini 等大模型读取，也可以自己留存、检索或继续处理。

如果这个工具对你有帮助，欢迎点个 Star。

目前源码版本：**v1.3.2**

支持私聊和群聊，可处理文字、长文本、引用回复、系统消息，并尽量导出本机仍有缓存的图片、文件、语音和视频。

## 下载

稳定版本：

[GitHub Releases](https://github.com/zhuzhangxue/wechat-chat-export/releases)

如果 Release 还没更新，也可以到：

[GitHub Actions](https://github.com/zhuzhangxue/wechat-chat-export/actions)

下载最新一次 `Build Windows EXE` 的 artifact。

Windows 版是单文件 EXE，不需要另外安装 Python。

目前没有商业代码签名证书，第一次运行时可能遇到 Windows SmartScreen 提示。仓库源码和构建脚本都是公开的，不需要为了运行本工具关闭 Defender、SmartScreen 或添加安全软件排除项。

## 使用

先登录 Windows 微信，并保持微信在后台运行。

打开程序后：

1. 输入好友的准确备注、昵称或群名；
2. 选择是否附带导出图片、文件、语音、视频；
3. 如有需要，指定微信数据目录；
4. 点击「开始导出」。

导出结果类似：

```text
exports/
└─ 某个聊天/
   ├─ chat_full_for_llm.txt
   ├─ chat_full_for_llm.md
   ├─ chat_full_parsed.json
   └─ media/
      ├─ images/
      ├─ files/
      ├─ voices/
      └─ videos/
```

其中：

- `TXT`：最适合直接交给大模型；
- `Markdown`：方便自己阅读，图片可直接显示；
- `JSON`：保留更多结构，适合脚本和二次开发。

程序还带有简单的聊天预览，可以直接查看文字和图片，并通过 Windows 默认程序打开文件、语音和视频。

导出成功后可以直接点击「打开聊天预览」查看刚刚导出的聊天；「预览已有聊天」则始终可用，可以随时选择以前的聊天导出文件夹重新打开预览。

## 微信数据目录

默认情况下程序会自动定位微信数据目录，一般不用手动设置。

如果自动探测选错了，或者电脑上存在多份微信数据，可以点击「微信数据目录」右侧的「选择」。

程序会列出发现的候选目录，并显示：

- 路径
- 账号数量
- 数据库最近修改时间
- 发现来源

候选会按数据库最近修改时间排序。找不到需要的目录时，也可以继续手动浏览。

这在下面几种情况比较有用：

- 微信数据迁移到了其他磁盘；
- 电脑上登录过多个账号；
- 存在旧的微信数据副本；
- 导出的最新消息明显早于微信里实际看到的消息。

下面这类路径都可以识别：

```text
D:\WeChatData
D:\WeChatData\xwechat_files
```

不填写时仍然使用自动探测。

命令行也可以手动指定：

```powershell
python cli.py "好友备注名或群名" --db-dir "D:\WeChatData"
```

## 图片、文件、语音和视频

媒体文件只能导出本机目前还保留着缓存的部分。

微信本地已经清掉的图片、文件或视频，本工具无法恢复。

语音导出时会尝试把微信 SILK 转成 WAV。正式 Windows EXE 已经包含所需的 `rust-silk` 解码器；转换成功后不会额外保留 SILK 中间文件。

## 本地语音转文字

「语音转文字（本地）」默认关闭。

勾选后会自动同时导出语音，并使用 SenseVoice 在本机完成识别。

第一次使用时需要下载约 230 MB 的 SenseVoice Small Int8 模型，模型默认保存在：

```text
%LOCALAPPDATA%\WeChat-Chat-Export-for-LLM\models\sensevoice
```

模型只需要下载一次，换新版 EXE 后仍可继续使用。

识别结果会缓存在：

```text
%LOCALAPPDATA%\WeChat-Chat-Export-for-LLM\cache\voice_asr_cache.json
```

重复导出同一条语音时可以直接复用。

识别过程在本机完成，不上传聊天语音。转写缓存里包含文字内容，不建议随意分享。

## 目前支持的内容

目前会尽量处理：

- 普通文字
- 长文本
- 引用回复
- 撤回和系统消息
- 群聊发送者
- 图片
- 文件
- 语音
- 视频
- 链接、卡片、位置、动画表情等常见消息

微信内部消息类型很多，少数特殊消息可能只能显示占位符；部分群成员昵称也可能无法完整还原。

## 从源码运行

推荐：

```text
Windows 10 / 11
Python 3.12
Windows 微信 4.1.12+
```

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

运行 GUI：

```powershell
python app.py
```

命令行：

```powershell
python cli.py "好友备注名或群名" --images --files --voices --videos
```

本地语音转文字：

```powershell
python cli.py --install-asr
python cli.py "好友备注名或群名" --transcribe-voices
```

### 源码运行时的语音解码

仓库不会直接提交 `rust-silk.exe` 这个第三方二进制文件。需要时会从 `rust-silk` 官方 Release 获取固定版本，并校验 SHA-256。

直接运行 GUI 源码时，如果第一次使用语音功能而本机没有 `rust-silk`，程序会询问是否自动下载。确认后会下载固定的 v0.1.3，并保存到：

```text
%LOCALAPPDATA%\WeChat-Chat-Export-for-LLM\tools\rust-silk.exe
```

命令行也可以先安装：

```powershell
python cli.py --install-rust-silk
```

也可以自己准备 `rust-silk.exe`，放在：

```text
wechat-chat-export\
└─ tools\
   └─ rust-silk.exe
```

如果没有安装或手动准备，语音仍可以导出为 SILK，但不能转换为 WAV，也无法继续做本地语音转文字。

正式 Windows EXE 会在 GitHub Actions 构建时自动下载并打包 `rust-silk`，普通用户不需要额外安装。

## Windows 构建

`.github/workflows/build-windows.yml` 会在 GitHub Actions 中构建 Windows EXE。

构建时会下载固定版本的 `rust-silk v0.1.3` 并校验 SHA-256，再和 Python 运行时及项目依赖一起打包。

SenseVoice 模型不会打进 EXE，只有用户主动开启本地语音转文字后才会下载。

底层微信数据库读取使用：

[`fanyuantaier/wechatauto-replica`](https://github.com/fanyuantaier/wechatauto-replica)

当前固定提交：

```text
04ef8cbde3862cff90b5f6b42c9ebfcea44ef48d
```

第三方组件和许可证见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。

## 隐私和限制

聊天记录只写到你选择的本地目录，本项目没有上传聊天内容的功能。

提交代码前仍建议自己检查 GitHub Desktop 的 Changes 或 `git status`。不要把真实聊天、微信数据库、解密密钥、媒体文件或语音转写缓存提交到 GitHub。

目前主要限制：

- 只支持 Windows；
- 当前面向 Windows 微信 4.1.12+；
- 同名联系人或群聊可能匹配歧义；
- 自动探测仍可能选错数据目录，这时可以重新选择或使用 `--db-dir`；
- 媒体只能导出本机仍有缓存的部分；
- 部分特殊消息和群成员昵称无法完整还原；
- 微信更新数据库结构或客户端实现后，项目可能需要继续适配。

遇到问题可以提交 Issue，但请先脱敏，不要直接上传真实聊天数据库、密钥或完整私人聊天记录。

## 免责声明

本项目是独立开源工具，与腾讯、微信（WeChat / Weixin）及其关联公司没有隶属、授权、认可或合作关系。

微信、WeChat、Weixin 及相关名称、商标归其各自权利人所有。

请只处理你本人有权访问和处理的数据，并自行遵守所在地法律法规、软件服务条款以及聊天参与者的隐私权。

软件按「现状」提供，微信版本、系统环境或上游依赖变化都可能导致功能失效或导出结果不完整。

## 开发与致谢

本项目的大部分早期设计、代码实现、问题排查和文档整理是在 ChatGPT 的协助下完成的。

项目由仓库维护者提出需求、进行实际环境测试并负责发布与维护，也欢迎社区贡献。

感谢 [fanyuantaier/wechatauto-replica](https://github.com/fanyuantaier/wechatauto-replica) 提供 Windows 微信 4.x 数据库读取与媒体处理等底层能力，本项目在其基础上完成聊天整理、媒体导出、预览和面向大模型的输出。

感谢 [@wzh4464](https://github.com/wzh4464) 提交 PR #1，为项目加入手动指定微信数据目录的支持，并完善相关路径兼容和异常处理。

## License

Apache License 2.0。

第三方依赖按各自许可证使用，见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。
