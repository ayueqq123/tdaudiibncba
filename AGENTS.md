# 开发约定

目标架构与验收基线:`docs/telegram-platform-architecture.md`。实现时以该文档为准,
与文档冲突时先确认再改。

## 硬规则

1. **GPL 边界**:`telegram-runtime/` 是 GPL-3.0 派生作品。禁止把该子树的代码复制进
   `telegram-platform/`;跨边界只走 HTTP/JSON 契约或共享数据库表。
2. **上游子树**:`telegram-runtime/` 与 `telegram-platform/` 的内核来自 `git subtree
   add --squash`。升级上游用 `git subtree pull`,不要手工整树覆盖;平台补丁直接写在
   子树内并在 `UPSTREAM.md` 登记。
3. **版本钉死**:Telethon 随 `telegram-runtime/requirements.txt` 钉在 `1.44.0`,
   升级必须连带回归 `_patch`、话题、实体格式、相册与发送返回值。
4. **副作用统一入口**:一切 Telegram 发送(create/edit/delete)必须经过账号 Worker 的
   SendPolicy 检查;不得保留绕过审批/停用/租约的发送路径。
5. **秘密不入库不入日志**:Session 明文、验证码、2FA 密码、API key 不进入数据库表、
   Celery payload、审计详情或日志。`.gitignore` 已覆盖常见形态,别绕开。
6. **不确定结果不盲重发**:投递状态机里的 `uncertain` 必须人工核查或按平台信息核验,
   不能自动当失败重试。

## 测试

- Python:`pytest`(后端与 runtime 各自运行)。
- 关键路径测试先用 Fake Telegram Transport + 固定事件集,再跑真实账号。
- 不为通过测试而修改测试,不做规避平台限制(FloodWait/防风控)的代码。

## 提交

- 每个 upstream subtree 的补丁单独成 commit,便于 `git subtree pull` 时分拣。
- 对应架构文档章节编号写进 commit message,例如 `[§7.4]`。
