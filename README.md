# 微信聊记录天导出

把 Windows 微信 4.1.12+ 里的聊天记录整理成 TXT、Markdown 和 JSON。可以直接拿去给大模型读，也可以留着做检索、整理或二次处理。

目前源码版本是 **v1.3.0**。

这个工具不是微信备份软件。它做的事情比较单一：从本机微信读取你能访问的聊天，把文字、引用、群成员、图片、文件、语音、视频等尽量整理成一套好读的导出结果。

## 怎么用

Windows 版不需要另外安装 Python。先登录 Windows 微信并保持微信在后台运行，然后打开程序，输入好友的准确备注、昵称或群名，选择要不要附带导出图片、文件、语音、视频，最后点「开始导出」。

媒体文件只会导出本机还留有缓存的内容。微信本地已经清掉的图片、文件或视频，程序也没办法凭空恢复。

导出完成后会得到类似这样的目录：

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

`TXT` 最适合直接上传给大模型；`Markdown` 方便自己阅读，图片会直接显示；`JSON` 保留的结构最多，适合脚本或后续开发。

程序里还有一个简单的「聊天预览」。图片直接显示，文件、语音和视频通过 Windows 默认程序打开，不需要在 VS Code 里点附件。

## 指定微信数据目录

程序默认自动定位微信数据目录，一般不用管这一项。

遇到下面这些情况，可以在界面的「微信数据目录」里填，或者命令行加 `--db-dir`：

- 在微信「设置 → 文件管理」里把数据目录迁到了别处，比如换到 D 盘；
- 这台机器登录过多个账号或装过多个版本，自动探测选中的不是你要的那个；
- 导出结果停在某个旧时间点，但微信界面里的聊天记录是新的。

最后一种通常说明自动探测读到了一份旧副本——数据目录放在 `%LOCALAPPDATA%` 下被沙箱化的应用写时复制过，或者放在 OneDrive 这类同步目录里。指到真实数据目录就能绕开。

填微信里显示的那个数据目录即可，下面两种写法都认：

```text
D:\WeChatData
D:\WeChatData\xwechat_files
```

## 语音和语音转文字

「语音」和「语音转文字（本地）」是两个选项。

只勾「语音」时，程序会把能找到的微信语音导出成 WAV。Windows 构建里自带 `rust-silk`，正常转换成功后不会额外留一份 SILK 中间文件。

勾「语音转文字（本地）」时，会自动同时开启语音导出，然后用 SenseVoice 在本机识别。这个功能默认关闭。

第一次使用本地转写时，程序会询问是否下载约 230 MB 的 SenseVoice Small Int8 模型。模型只需要下载一次，默认放在 `%LOCALAPPDATA%\WeChat-Chat-Export-for-LLM\models\sensevoice`，以后换新版 EXE 也可以继续用。语音识别本身在本机完成，不上传聊天语音。

识别结果也会做本地缓存，默认放在 `%LOCALAPPDATA%\WeChat-Chat-Export-for-LLM\cache\voice_asr_cache.json`。重复导出同一条语音时会直接复用。这个缓存删掉也没关系，只是下次需要重新识别；它包含转写文字，所以不要随便分享。

## 目前处理的内容

普通文字、长文本、引用回复、撤回和系统消息都尽量恢复成可读内容。群聊会尽量还原真实发送者，而不是只留一个 `wxid`。

图片、文件、语音和视频可以导出本体；链接、卡片、位置、动画表情等消息会尽量保留标题或可读描述。微信内部消息类型很多，少数特殊卡片仍可能只能显示占位符。

图片和视频的本地缓存格式也不完全统一，所以导出是否成功取决于本机还保存着什么。程序不会为了补媒体内容去登录云端或上传聊天。

## 下载和构建

稳定发布包放在 [Releases](https://github.com/zhuzhangxue/wechat-chat-export/releases)。如果 Releases 里的版本暂时落后于源码，也可以到 [Actions](https://github.com/zhuzhangxue/wechat-chat-export/actions) 下载最新一次 `Build Windows EXE` 的 artifact。

当前 EXE 没有商业代码签名证书，第一次运行可能遇到 Windows SmartScreen 提示。仓库源码和 GitHub Actions 构建脚本都是公开的；不想运行未签名程序的话，可以直接从源码运行或自己构建。没必要为了这个工具关闭 Defender、SmartScreen，也不建议给目录加安全软件排除项。

## 从源码运行

推荐 Windows 10/11、Python 3.12、Windows 微信 4.1.12+。

```powershell
python -m pip install -r requirements.txt
python app.py
```

命令行也可以用：

```powershell
python cli.py "好友备注名或群名" --images --files --voices --videos
```

如果想在命令行使用本地语音转文字：

```powershell
python cli.py --install-asr
python cli.py "好友备注名或群名" --transcribe-voices
```

需要手动指定微信数据目录时：

```powershell
python cli.py "好友备注名或群名" --db-dir "D:\WeChatData"
```

## Windows 构建

`.github/workflows/build-windows.yml` 会在 GitHub Actions 的 Windows 环境里打包单文件 EXE。

构建时会固定下载 `rust-silk v0.1.3` 的 Windows x64 文件并校验 SHA-256，再和 Python 运行时、`sherpa-onnx`、微信数据库读取依赖等一起打进 EXE。SenseVoice 模型本身不打进 EXE，只有用户主动开启本地转写并确认后才下载。

底层微信数据库读取使用 [`fanyuantaier/wechatauto-replica`](https://github.com/fanyuantaier/wechatauto-replica)，目前固定在提交：

```text
04ef8cbde3862cff90b5f6b42c9ebfcea44ef48d
```

其他第三方组件和许可证见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。

## 隐私和已知限制

聊天记录只写到你选择的本地目录。项目没有把聊天内容上传到服务器的功能；本地语音识别下载的是模型文件，识别过程本身在电脑上完成。

使用前仍建议保留微信原数据，不要把导出目录、数据库、密钥或真实私人聊天内容提交到 GitHub。仓库的 `.gitignore` 能挡住一部分常见文件，但不能代替自己检查 `git status`。

目前主要限制是：只支持 Windows，目前按上游兼容范围面向 Windows 微信 4.1.12+；同名联系人或群聊可能匹配歧义；自动探测可能选错数据目录，这时需要手动指定 `--db-dir`；部分特殊消息和群成员昵称无法百分之百还原；媒体只能导出本机仍有缓存的部分；微信更新数据库结构后也可能需要跟着适配。

遇到解析问题可以提交 Issue，但请先脱敏，不要直接上传真实聊天数据库、密钥或完整私人聊天记录。

## 免责声明

本项目是独立开源工具，与腾讯、微信（WeChat / Weixin）及其关联公司没有隶属、授权、认可或合作关系。微信、WeChat、Weixin 及相关名称、商标归其各自权利人所有。

请只处理你本人有权访问和处理的数据，并自行遵守所在地法律法规、软件服务条款以及聊天参与者的隐私权。软件按「现状」提供；微信版本、系统环境或上游依赖变化都可能导致功能失效或导出结果不完整。

## License

Apache License 2.0。第三方依赖按各自许可证使用，见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。
