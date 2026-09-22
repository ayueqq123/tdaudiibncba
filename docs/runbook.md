# TG 平台运维手册(Runbook)

面向值班/交付运维。平台组件:`control-api`(FBA)、`task-worker`(celery)、`scheduler`(celery beat)、`tg-runtime-worker`、`langbot`、`postgres`、`redis`、`web`、`reverse-proxy`。部署拓扑见 `deploy/README.md`。

## 1. 启动/停止

```bash
cd deploy && cp .env.example .env   # 填 CHANGE_ME
docker compose --env-file .env up -d postgres redis
docker compose --env-file .env run --rm control-api fba init   # 首次:迁移+种子
docker compose --env-file .env up -d                            # web/control-api/task-worker/scheduler
docker compose --env-file .env --profile runtime up -d          # tg-runtime-worker
docker compose --env-file .env --profile ai up -d               # langbot
```

健康检查:`GET /api/v1/sys/heartbeat`(401 即存活)、`docker compose ps` health 列。

## 2. RBAC 权限点清单

tg 路由权限点(RequestPermission 强制,超级管理员自动放行):

| 权限点 | 操作 |
|---|---|
| tg:tenant:add / edit / del | 租户管理 |
| tg:project:add / edit / del | 项目 |
| tg:membership:add / edit / del | 项目成员 |
| tg:account:import / edit / del | 账号导入、期望状态、删除 |
| tg:rule:add / edit / del / publish | Clone 规则 + 发布快照 |
| tg:delivery:retry / cancel | 投递重试/取消 |
| tg:approval:create / decide | 候选创建、审批决策 |
| tg:command:issue | 运行时命令下发 |
| tg:ai:binding:edit | AI 绑定注册 |
| tg:ai:run:trigger / cancel | AI 手动触发/取消 |

已知例外(按设计):
- `POST /api/v1/tg/internal/ai/langbot/{uuid}/callback` — 无 JWT,HMAC-SHA256 验签(binding 决定租户)。
- `GET /api/v1/tg/runtime/accounts/{id}/rules|commands`、`POST .../commands/{id}/ack` — JWT 鉴权。**生产增强**:换独立 service 凭据/mTLS,现依赖 JWT 强校验。
- `POST /api/v1/tg/clone-rules/{id}/dry-run` — JWT-only,零副作用。

## 3. AI 链路排障

链路:`trigger → ai_run(dispatched) → LangBot → ai_callback(seq) → reply_candidate → approval → delivery_job(ready)`。

| 症状 | 查 | 处理 |
|---|---|---|
| run 卡 `dispatched` | `tg_ai_run.deadline` 已过 | `sweep_deadlines` → incomplete;查 LangBot 容器日志/模型供应商 |
| run `incomplete` + `gap:` | `tg_ai_callback` 缺 seq | LangBot 重试可回填;若缺段不可恢复,重触发(新 context_epoch 视需要) |
| run `failed` + `transport:` | LangBot 不可达 | 查 app 网段连通性;恢复后重新 trigger |
| callback 返回 401 | 签名错 | 核对 binding outbound_secret_ref 与 LangBot HTTP_BOT_OUTBOUND_SECRET 一致 |
| 候选一直 pending | 审批队列 | 审批人处理;过期自动 expired |

取消 run:`POST /api/v1/tg/ai/runs/{id}/cancel`(只拦本地发送,远端推理不保证停)。

上下文重置:删除会话记录或让 `context_epoch+1`(目前由新会话 epoch 递增;LangBot 侧 `/bots/{uuid}/reset` 由适配器封装)。

## 4. 账号与租约

| 症状 | 查 | 处理 |
|---|---|---|
| 账号 `auth_dead` | telegram_account.observed_status | 需重新导入/人工补登;不自动重试 |
| `takeover_blocked` | account_lease holder_alive | 另一 worker 持有且活着;确认旧 worker 死后再接管 |
| FloodWait | delivery_job.flood_wait_until | 按 (account,method_class,peer) 等待;不整账号阻塞 |

**导入号必做**:2FA 轮换 + 踢其他已授权会话(`ResetAuthorizations`),否则号不算独占。

## 5. 备份/恢复

`deploy/backup/backup.sh`(pg-backup profile)→ `/backups/*.dump` + sha256 manifest,保留 14d。
恢复演练:`restore.sh <dump>` → 影子库 `*_restore_check` → 行数抽查 → 人工切换。**警告:恢复不能撤回已发送的 Telegram 副作用**;不一致时以平台真相源标记 job 状态,不盲重发。每季度演练一次,记录在 §7。

## 6. Metrics

`control-api` 暴露 `/metrics`(FBA prometheus_client 挂载)。tg 域指标:

- `tg_ai_callback_total{result}` — linked/pending_link/dedup/rejected
- `tg_ai_run_total{status}` — completed/incomplete/failed/cancelled
- `tg_ai_run_active` — 生成中 run 数
- `tg_delivery_job_created_total{kind}` — 平台建任务数

Prometheus 抓取配置:`deploy/prometheus/prometheus.yml`。标签只用低基数枚举(§18.1)。

## 7. 灾难恢复演练记录模板

| 日期 | 演练人 | 备份 dump | 影子库校验 | 切换耗时 | 发现的问题 | 跟进 |
|---|---|---|---|---|---|---|
| | | | | | | |

## 8. 全局停用

AI 半边停:`docker compose --profile ai stop langbot` + 绑定的 `status=disabled`。
账号侧停:`telegram_account.desired_status='stopped'`(worker 摘租约);紧急全停:停 `tg-runtime-worker` 服务。
