# D0 Spike:LangBot 上下文注入可行性

**基线**:langbot-app/LangBot @ `b10139bd831cb457cf28a4a73995c6c099817864`(源码审查,非运行态)
**结论**:**可行,但注入点必须在我们平台侧,不在 LangBot 内部**。见下方依据与方案。

## 验证项

### 1. HTTP Bot 入站/回调契约 ✅(与架构文档一致)

源码:`src/langbot/pkg/platform/sources/http_bot.py`

- 入站:`POST /bots/{bot_uuid}` — 验签(HMAC-SHA256 timestamp+body)后返回 `202` + `accepted_message_id`;`{session_id, message}` 必填;`Idempotency-Key` 头 → 409 幂等拒绝(10 分钟窗口,4096 条上限)。
- `/bots/{bot_uuid}/sync` 子路径:同步等待一个 turn 的最终回复(收齐 `is_final` 后一次返回)。可作调试/对账通道。
- `/bots/{bot_uuid}/reset`:`{session_id}` → 丢弃会话(下次消息开新对话)。
- 出站回调:每个 `reply_message`/`reply_message_chunk` 一个签名 POST 到配置的 `callback_url`;**按 session 有序**(per-session worker queue + `sequence` 计数,`is_final` 标记 turn 结束);5xx/网络错误指数退避重试(默认 3 次,timeout 15s)。
- SSRF:callback_url 只来自 adapter config,不接受消息内字段 — 符合我们的安全模型。
- `send_message(target_id)` 支持主动推送(target_id == session_id)。

### 2. 会话历史 = 纯进程内,无注入接口 ❌(关键发现)

源码:`src/langbot/pkg/provider/session/sessionmgr.py`

- `SessionManager._session_index` 是内存 dict;`conversation.messages` 只活在该进程里,restart 即丢。
- 入站 `_build_event` 只读 `session_id`/`sender`/`message` — **payload 没有 history 字段**。
- 全仓无"向已有 session 注入历史消息"的 API(monitoring/controller 只有读取和 reset)。
- 架构文档 §9.4 假设的"受控 context bridge 一次注入 LangBot 会话历史"**不成立**。

### 3. 可行方案:上下文随消息内嵌(平台侧 bridge)✅

不依赖 LangBot 会话状态,把上下文作为**消息内容的一部分**在每个 turn 携带:

- 每次入站 message 前部附加结构化上下文块(如 `[上下文] user[123]@14:02: ...`),平台侧从 `message_map`/`source_message`/`ai_run` 重建;LangBot 只当普通 user 消息处理。
- 优点:restart 免疫(我们才是真相源)、确定性回放、与 per-session 隔离(session_id 由我们定)天然契合、不依赖 LangBot 内部 API。
- 代价:每 turn 重放历史 → token 成本线性增加;需平台侧做窗口截断(按条数/token 预算)和敏感信息剥离;回调序仍需我们侧按 `sequence`+`is_final` 去重补段。

### 4. 插件禁用面 ✅

`plugin.enable: false`(templates/config.yaml)→ 整个插件子系统关闭。其余 pipeline 阶段(bansess/ratelimit/preproc/cntfilter/longtext/respback/msgtrun)均 config 驱动,可逐项关 — 我们部署时只保留 process(LLM 调用)+ respback。

### 5. 回调乱序/缺段处理(我们侧已有设计,结论吻合)

- `sequence` 单调递增;queue 满 100 时**丢最旧**(非阻塞)— 我们的 receiver 必须按 `(bot_uuid, session_id, reply_to, sequence)` 检测缺段并向 LangBot 重发该轮或标 `callback_gap`(§9.2 已有)。
- `is_final: true` = turn 结束信号;超时未到即 turn 不完整。

## 对架构文档的影响(待 D1 落地时修订)

- §9.4 "受控 context bridge" → 改为"**平台侧上下文内嵌**:每次 ai_run 重建上下文注入到 inbound message;LangBot 会话不承担持久性"。
- 新增验收项:LangBot 重启后无状态恢复能力由平台保证(平台重发含上下文的 inbound message)。
- `ai_run` 需要 `context_window` 字段记录本次注入的上下文条数/截断策略,便于审计与预算。
