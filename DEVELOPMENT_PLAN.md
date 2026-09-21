# 开发计划

按 `docs/telegram-platform-architecture.md` §17 的批次拆成可独立评审的 PR。
每个 PR 不破坏 main 的可测试状态;顺序大致按依赖,允许并行推进的部分标注。

已完成:PR#1 架构文档(Session 导入设计)/ PR#2 协议号导入模块 / PR#3 runtime 管线骨架(ingest→planner→delivery/policy/executor)。

## 阶段 A:runtime 持久化与工作循环

| PR | 范围 | 退出条件 |
| --- | --- | --- |
| A1 | `runtime/storage`:SQLAlchemy 模型(source_message、event_inbox、delivery_job、delivery_attempt、message_map、album_group/item、account_lease、import_batch)+ MappingRepository + §6.4 五段事务边界的仓储方法 | sqlite 可建表;仓储单测覆盖映射写入/反查/删除 tombstone、job 领取原子性、唯一约束幂等 |
| A2 | `runtime/account`:Session 信封加密(secret_ref + KMS stub)、租约心跳(45s 租约、generation CAS)、RuntimeController 命令消费(start/stop/reload/drain) | 加密往返可验;租约抢占/失效测试通过;命令幂等 |
| A3 | `runtime` worker 主循环:Telethon adapter(RawUpdate 边界)→ event_inbox → planner → delivery_job → SendPolicy → executor → 结果事务落库 | FakeTransport 全链路测试:create/edit/delete/相册/uncertain 路径;重启恢复未完成任务 |

## 阶段 B:控制面(FBA)

| PR | 范围 | 退出条件 |
| --- | --- | --- |
| B1 | `telegram-platform/backend`:FBA 环境跑通(venv/uv.lock、Postgres+Redis docker-compose、迁移基线)+ tenant/project/membership 模型 | FBA 测试通过;compose 起栈;新模型迁移可应用可回滚 |
| B2 | 账号域:telegram_account + import_batch 模型、`POST /accounts/import` + `GET /imports/{batch_id}`、审计事件 | 导入 API 端到端(校验编排调用 runtime importer),跨项目访问拒绝测试 |
| B3 | 规则域:clone_rule/version/target 模型 + dry-run/publish、runtime_command 下发 | 发布产生不可变快照;Worker 能拉到;版本乐观锁生效 |
| B4 | 投递与审批查询:deliveries 列表/详情、retry/cancel、approvals approve/reject | 每目标状态可见;uncertain 不能走普通重试;审批绑定 hash+有效期 |

## 阶段 C:前端与部署

| PR | 范围 | 退出条件 |
| --- | --- | --- |
| C1 | `telegram-platform/web`:账号/导入/规则/投递记录页面骨架(复用 FBA UI 布局与权限) | 页面可操作 API;权限按钮真实受控 |
| C2 | `deploy/`:docker-compose 拓扑(edge/app/data/ops 四网段)、健康检查、备份脚本与恢复演练文档 | compose 全栈起;一次备份恢复演练记录 |

## 阶段 D:AI 与生产化(依赖外部验证)

| PR | 范围 | 退出条件 |
| --- | --- | --- |
| D0(spike,尽早) | LangBot 上下文注入可行性:HTTP Bot 回调序、context 重建接口、插件禁用面 | 书面结论:注入可行/不可行 + 依据;不可行则 AI 方案重排 |
| D1 | ai_run/ai_callback/reply_candidate/approval 模型 + LangBotEngineAdapter | 回调去重/缺段/过期测试;候选不可变 |
| D2 | 审批工作台 API + 统一发送接入 delivery_job | 拒绝不发、过期不发、修改重审全通过 |
| D3 | RBAC 全路径、metrics、告警、备份恢复、运行手册 | 上线硬门槛清单逐项过 |

## 当前阻塞/待你确认

1. ~~推送权限~~ 已用 PAT 解决。
2. LangBot 模型供应商选型与预算(D0 需要)。
3. 生产部署环境:你的服务器规格、密钥服务(KMS/Vault 或文件密钥)。
4. 第二阶段 SaaS 先不做,按计划单客户私有化。
