# 微信聊天记录导出

把 Windows 微信 4.1.12+ 的聊天记录导出为 TXT、Markdown 和 JSON，方便交给 GPT、Claude、Gemini 等大模型读取，也可以自己留存、检索或继续处理。

如果这个工具对你有帮助，欢迎点个 Star。

目前源码版本：**v1.3.4**

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

发送者身份按消息来源分片的 `Name2Id` 解析，再映射显示名；只有稳定账号 `username` 与本机账号一致才显示为“我”，不根据数字 ID 或昵称猜测。私聊映射到双方以外的账号、缺少映射等情况会显示“未知发送者”并在导出日志中汇总警告。群聊只剥离与已解析发送者 ID 一致的正文前缀，无法确认时保留原文。

JSON 保留原有字段，并增加每条消息的 `source_db`、`real_sender_id`、`server_id`、`sender_username`、`is_self`（无法判断时为 `null`）、`sender_status`，以及顶层的 `sender_resolution_counts`，便于本地复查。无法确认本机账号时不判断“我”，解析状态会标记不确定。

v1.3.3 修复了旧版本在跨多个消息数据库分片导出时可能出现的发送者名称错误映射。如果你曾使用 v1.3.2 或更早版本导出大量历史记录，建议使用 v1.3.3 重新导出。旧导出不会自动更新，重新导出时建议选择新的输出目录，避免覆盖旧结果。

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

## 敏感临时缓存

v1.3.4 起，程序不会再直接使用 `wechatauto-replica` 默认的长期临时工作目录。每次导出都会创建独立的一次性工作目录，用于暂存数据库解密密钥、图片 AES key 和解密后的数据库缓存：

```text
%TEMP%\wechat-chat-export-sensitive\run-...
```

无论导出成功还是正常报错退出，程序都会尝试删除这整个一次性目录。这里的目标是避免敏感解密材料在导出完成后长期留在磁盘上。

GUI 启动和开始新导出时，还会自动检查本项目自己的 `%TEMP%\wechat-chat-export-sensitive\run-*` 残留。新版工作目录带有进程所有权标记：只有确认对应进程已经不存在的目录才会立即自动删除；仍有活动进程的目录会跳过。为兼容此前测试版留下的无标记目录，仅在目录超过 24 小时后自动清理。**自动清理不会触碰旧版共享的 `%TEMP%\wechatauto_db`。**

这不是内存盘，也不是 DPAPI 加密：**导出正在运行时，这些临时数据仍可能以明文形式存在于当前 Windows 用户的临时目录中。** 如果进程被强制结束、系统断电，或文件被其他程序占用，仍可能留下残余缓存；下一次启动/导出会再次尝试清理本项目自己的失效残留。

v1.3.3 及更早版本使用上游默认目录，旧缓存可能仍位于：

```text
%TEMP%\wechatauto_db\<账号>\
```

其中可能包含 `keys.json`、`image_keys.json` 和解密数据库缓存。

GUI 中可以点击「清除敏感缓存」进行显式清理。命令行也可以使用：

```powershell
python cli.py --clear-sensitive-cache
```

清理功能会同时尝试删除当前版本的临时缓存根目录和旧版 `%TEMP%\wechatauto_db`。旧版目录也可能被其他直接使用 `wechatauto-replica` 的程序共用，因此执行清理前请先关闭这些程序。

清理不会删除微信原始聊天数据库，也不会删除已经导出的 TXT、Markdown、JSON 或媒体文件。

## 图片、文件、语音和视频

媒体文件只能导出本机目前还保留着缓存的部分。

微信本地已经清掉的图片、文件或视频，本工具无法恢复。

v1.3.4 同时补充了微视频 / 视频号处理：

- 普通视频和兼容的微视频类型会继续尝试从本机视频缓存导出；
- 视频号分享（常见为 `local_type 49` + `appmsg type 51`）会解析 `finderFeed`；
- `chat_full_parsed.json` 会在对应消息中增加 `finder_feed`，保留视频号作者、描述、对象 ID、媒体 URL、封面、尺寸和时长等结构信息；
- 勾选“视频”后，程序只会在能够可靠对应到现有本地视频文件时导出视频本体，不会用时间、文件大小或相似文件名去猜测；
- Windows 微信 4.1.12 的真实验证中，视频号播放后的缩略图可以进入 Chromium HTTP cache，但视频本体没有通过当前可安全只读访问的 `message_resource.db`、`hardlink.db` 或普通 Chromium disk cache 建立可靠本地映射；
- 视频号 CDN 视频还需要与该视频 URL 配对的运行时解密信息。当前本地只读模式无法从已验证的持久化数据中可靠取得这组信息，因此未匹配到本地视频时会明确标记为不可用；
- 当前不会因为视频号消息而自动联网下载 CDN、调用私有接口、安装证书、代理微信流量或猜测缓存文件，避免把“本地导出”变成隐式网络行为。

视频号 `finder_feed` 中可能包含临时 CDN URL 等资源信息。导出的 JSON 本身就是聊天数据的一部分，不建议未经脱敏直接公开分享。以后如果增加视频号在线获取能力，应作为默认关闭、明确提示联网与敏感数据处理的独立高级功能，而不是改变当前本地只读导出的默认行为。

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
- 普通视频、微视频和视频号分享
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

v1.3.4 起，数据库密钥、图片密钥和解密数据库缓存使用一次性临时工作目录，并在导出结束或正常报错时尝试自动清理。强制结束进程、系统断电或文件占用仍可能导致临时缓存残留，可使用「清除敏感缓存」或 `--clear-sensitive-cache` 手动清理。

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

感谢 [@EnTaroYan](https://github.com/EnTaroYan) 提交 Issue #2 和 PR #4，定位并修复跨消息数据库分片时的发送者身份映射错误，并补充相关回归测试。

感谢 [@peterforeternity](https://github.com/peterforeternity) 提交 Issue #6，指出旧版本本地敏感解密缓存长期残留的风险，并反馈视频号/短视频导出限制。

## License

Apache License 2.0。

第三方依赖按各自许可证使用，见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。

### 自动清理异常残留（v1.3.4）

正常导出完成或常规报错时，程序仍会立即删除本次使用的敏感临时工作目录。除此之外，GUI 启动和下一次导出开始前还会自动检查本项目专属的 `%TEMP%\wechat-chat-export-sensitive\run-*` 残留：带进程标记且对应进程已经不存在的目录会自动清理；仍有活动进程的目录会跳过。此前测试版产生的无标记目录采用更保守的策略，仅在超过 24 小时后自动清理。

自动清理**不会**删除旧版共享的 `%TEMP%\wechatauto_db`，该目录仍只通过“清除敏感缓存”按钮或 `--clear-sensitive-cache` 由用户明确清理，避免误伤其他直接使用 `wechatauto` 的程序。
