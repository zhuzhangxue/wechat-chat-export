# 真实环境验证脚本（开发者自测用）

这些脚本**会读取本机正在登录的 Windows 微信数据**，用于在真实数据库上验证导出行为；
不属于 `tests/` 单元测试，CI 不会运行。

| 脚本 | 内容 |
| --- | --- |
| `real_env_check.py` | 聊天列表、多选导出、与 main 分支逐字节回归对比、多时间段筛选（独立实现交叉验证）、时间段 + 图片、同名解析统计、每个阶段后的敏感缓存检查 |
| `old_runner.py` | 由 `real_env_check.py` 调用：用 `git archive HEAD` 得到的基线代码导出同一批会话，作为回归对照 |
| `gui_e2e.py` | 图形界面端到端：真实读取聊天列表 → 选择窗口勾选 2 个会话 → 导出 → 检查完成提示与残留 |

```powershell
# 先登录并保持 Windows 微信运行
python tools/real_env_check/real_env_check.py
python tools/real_env_check/gui_e2e.py
```

- 回归对照的基线是**当前仓库的 HEAD 提交**，请在未提交改动的工作区、或以 main 为 HEAD 时运行；
- 自动挑选 24 小时内没有新消息的 2 个私聊和 1 个群聊，避免对比期间收到新消息导致误报；
- `report.json` / `gui_report.json` 只含计数和通过 / 失败，不含聊天名、username、内容或具体日期；
- `private/` 目录包含真实聊天导出和测试对象的 username，已在 `.gitignore` 中忽略，**不要上传**，用完可直接删除。
