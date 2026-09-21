# Telegram 自动化平台开发架构

版本：v1.0 · 设计日期：2026-09-21 · 用途：开发拆解、技术评审与生产验收基线。

**确定的技术路线：FBA 管理后台 + telemirror 派生运行时 + PostgreSQL 持久化任务与消息映射 + Redis/Celery 辅助任务 + LangBot HTTP Bot AI 接入。** Clone 优先复用 telemirror 的消息、相册、格式、过滤与话题处理，在其周围补齐多账号、可靠投递、审核、权限与运维能力。

这份文档是目标架构，不是已经实现的系统。标记为“现状”的内容来自指定提交的源码；服务名称、数据库表、内部接口、状态机和验收指标均为本方案拟建内容。未使用真实 Telegram 账号运行验证，性能数字均为待验证目标。

## 1. 架构决策与第一阶段范围

### 1.1 必须先定下来的八个决策

| 决策 | 本方案默认值 | 原因与边界 |
| --- | --- | --- |
| 产品组织方式 | 第一阶段每客户独立部署；模型从第一天包含 tenant/project | 降低首次交付的隔离复杂度；第二阶段共享 SaaS 仍需单独验收 |
| 控制面 | 一个模块化 FBA 后端，配套 Vue 管理前端 | 复用用户、角色、日志、任务基础；不提前拆成大量微服务 |
| Telegram 运行时 | 一个账号一个独立进程/容器；同账号 Clone、AI 共用连接 | 避免两个程序同时持有同一 Session；先保证故障隔离 |
| Clone 引擎 | 维护 telemirror 的 GPL 派生仓库 | 复用核心处理逻辑，明确补丁与上游版本，不在业务后台散落复制源码 |
| 收发关系 | 同一账号读取源群并向目标群发送 | 上游明确不支持不同 receiver/sender；账号必须同时有源读取和目标发送权限 |
| 投递语义 | 持久化任务、重复处理可恢复、结果不确定时暂停核查 | PostgreSQL 事务无法覆盖 Telegram 外部发送，不能承诺端到端“恰好一次” |
| AI 模式 | 显式触发，默认人工审核，LangBot 只返回候选内容 | 统一账号队列发送；模型、插件和 LangBot 均不直接操作 Telegram |
| 第一阶段数据库 | PostgreSQL 为事实来源；Redis 为缓存与 Celery broker | Redis 故障不能丢失消息映射、审批、投递任务和账号归属 |

首期优先支持频道、超级群和论坛话题；普通小群可配置接收和发送，但删除同步只提供有限支持并在界面提示。私聊、陌生用户私信、自动拉群、跨账号接力收发、匿名伪装、规避平台限制均不纳入本架构。

### 1.2 第一阶段必须交付

- Web 登录、角色与项目授权、操作审计、账号登录/2FA/退出、Session 管理、群目录与授权状态。
- 多账号独立运行与状态监控；每条 Clone 规则绑定一个具体账号，一个源群可投递多个目标。
- 文本、图片、视频、文件、相册；copy/forward 模式；关键词、替换、格式、话题和回复引用；编辑与删除处理。
- PostgreSQL 消息映射、持久化发送任务、按目标重试、死信、结果不确定处理、重启恢复与循环防护。
- Agent、统一 AI 引擎适配、上下文、回复策略、单个实际模型供应商、最小审核队列、频控、黑白名单、全局停用。
- Docker 部署、Redis、后台任务、健康检查、错误告警、备份与实际恢复演练。

第二阶段再交付共享多租户、多项目自助管理、多个模型供应商的运营能力、Agent 模板、复杂规则、完整定时任务界面、审核工作台、WebSocket 实时日志、统计和租户级自助恢复。**最小审核与备份恢复属于第一阶段生产前置条件。**

## 2. 总体架构与服务边界

```text
客户浏览器
    │ HTTPS
    ▼
反向代理 ── Vue 管理后台
    │
    ▼
FBA Control API
    ├── 身份 / 项目权限 / 账号元数据 / 规则版本 / Agent
    ├── 审核 / 全局开关 / 审计 / 查询 / 命令受理
    └── PostgreSQL：控制表 + 持久化命令 / 事件 / 投递表
                          │
              ┌───────────┴────────────┐
              ▼                        ▼
Account Supervisor               Outbox Dispatcher
    │ 启停、归属、恢复                  │ 通知有限任务
    ▼                                 ▼
账号 Worker A / B / ...          Redis → Celery Worker
    ├── 唯一 Telethon 连接              ├── AI 请求编排
    ├── telemirror 派生 Clone 引擎      ├── 媒体分析 / 清理
    ├── 事件落库 / 消息映射             └── 通知 / 汇总
    ├── 账号串行发送队列                         │
    └── 最终权限、审批、停用检查                  ▼
           │                            LangBot HTTP Bot
           ▼                                  │
       Telegram                         模型供应商 API
                                              │
                             签名回调 → FBA AI Gateway
                                              │
                                   候选回复 → 审核 → 投递表

共享基础设施：PostgreSQL / Redis / 加密对象存储 / 密钥服务
可观测性：结构化日志 / Prometheus / Grafana / 错误追踪
```

### 2.1 部署单元

| 单元 | 持有的状态与职责 | 不能承担的职责 |
| --- | --- | --- |
| `web` | FBA 配套 Vue UI；账号、规则、Agent、审核、任务、日志页面 | 不接触 Session 明文，不直接调用 Telegram/LangBot 管理 API |
| `control-api` | FBA 模块化后端；权限、配置、命令、审核、业务查询；AI Gateway 可先作为其中模块 | 不持有长期 Telegram 连接，不用 HTTP 请求同步等待大文件发送 |
| `supervisor` | 核对 desired/observed 状态；绑定账号与 Worker；优雅停机、重启和隔离 | 不是发送者，不绕过账号权限，不把租约过期等同于旧进程已停止 |
| `telegram-runtime` | telemirror 派生代码、一个账号的 Telethon 连接、事件和投递处理 | 不执行 LLM 推理，不接受公网任意发送指令 |
| `dispatcher` | 扫描 PostgreSQL outbox/待处理业务任务；投递通知、补发通知 | 不把 broker 确认当成业务成功，不承担 Telegram 长连接 |
| `task-worker` | Celery；AI 请求、分析、通知、离线汇总等有限任务 | 不为每个任务新建用户账号连接，不重复执行未知结果的发送 |
| `scheduler` | 单活调度器；生成清理、同步、备份提醒与到期任务 | 不直接发送消息；到期只创建命令/任务 |
| `langbot` | 模型与 pipeline、Agent 运行、隔离会话与上下文；HTTP Bot 回调 | 不装 Telegram Session，不启用其 Telegram Bot 直接发言路径 |
| `postgres / redis / object-store` | 持久化业务、任务缓存与媒体对象 | 无公网数据库端口；媒体不以公共 URL 长期暴露 |

这些是职责边界，不要求首期全部独立主机。`dispatcher`、`scheduler` 和 `task-worker` 可以复用后端镜像，以不同启动命令运行；Telegram runtime 和 LangBot 使用各自镜像、依赖锁与数据库凭据。

### 2.2 控制面与运行面的数据契约

- FBA 负责写规则、审批、账号 desired state 和 `runtime_command`；Worker 负责更新 observed state、事件、投递尝试和映射。
- 第一阶段允许服务共享 PostgreSQL 实例，但划分 `control`、`runtime` 等 schema 和最小权限数据库角色；**数据库 schema 不是租户隔离保证**。
- runtime 只读发布后的规则快照，不能修改平台用户、角色、模型密钥或审批结论；它只能读取验证发送所需的审批元数据。
- LangBot 独立数据库/数据库用户，由自身迁移管理；FBA 通过受控集成管理 bot/pipeline 关联，不直接写 LangBot 内部业务表。
- 内部 HTTP 使用服务身份认证；任务里的 `tenant_id` 只是声明，消费者仍要通过账号绑定、任务归属和数据库关系验证。

## 3. 技术栈与版本策略

| 层 | 建议 | 版本与兼容策略 |
| --- | --- | --- |
| 后台 | FBA、FastAPI、Pydantic、SQLAlchemy、Alembic | 固定 FBA 提交和项目锁文件；在其模块边界内增加业务 |
| 前端 | FBA 配套 Vue/Vben UI、TypeScript | 沿用配套前端包管理器、锁文件和构建工具，不混用 LangBot React UI |
| Telegram | telemirror 派生仓库 + Telethon | 调研提交固定 `telethon==1.44.0`，Docker 使用 Python 3.13；先维持兼容组合 |
| AI | LangBot、HTTP Bot、一个模型供应商 | 固定 LangBot 提交及 SDK 依赖；通过 HTTP 集成，避免 Python 依赖冲突 |
| 数据 | PostgreSQL、Redis、S3 兼容存储 | PostgreSQL 可从 16 系列评估，落地固定补丁版本/镜像摘要；迁移与驱动兼容需验证 |
| 异步 | PostgreSQL delivery/outbox + Celery/Redis | Telegram 发送使用账号 Worker；Celery 只运行有限业务任务 |
| 部署与监控 | Docker Compose 起步；反向代理、Prometheus/Grafana、日志系统 | 高可用阶段再引入容器编排；所有生产镜像固定版本或摘要 |

不能仅凭依赖声明认定三个项目在一个 Python 环境中兼容。分镜像构建、独立锁依赖；升级 Telethon 时特别回归 telemirror 的 `_patch`、话题、实体格式、相册和发送返回值。

## 4. telemirror 的具体复用方案

### 4.1 已核实的源码现状

核实基线：[telemirror `19cf3ace`](https://github.com/khoben/telemirror/tree/19cf3acee1003191b7a30e337ee6cab95e59c2f9)。

| 位置 | 现状 | 对架构的影响 |
| --- | --- | --- |
| `Telemirror` / `Mirroring.run()` | 一个 StringSession 创建同一个接收/发送客户端；不同 receiver/sender 会抛错 | 首期一账号负责一条规则的完整收发；不承诺跨账号桥接 |
| `EventHandlers` | 注册 NewMessage、Album、MessageEdited、MessageDeleted；新消息跳过相册成员 | 复用事件分类，但改为先落事件和任务，不能直接调用现有发送路径 |
| `EventProcessor` | 遍历目标、运行过滤、发送、再插映射；多处捕获异常只记日志 | 需拆开“计划”和“副作用执行”，让单目标结果和失败可持久化 |
| `edit_message()` | forward 模式跳过编辑；copy 模式调用编辑接口 | UI 必须显示模式能力；forward 不承诺内容编辑同步 |
| `delete_message()` | 删除异常后仍走映射清理；循环变量 `message_ids` 覆盖输入源消息 ID | 必须改为按目标记录结果与 tombstone；源 ID/目标 ID 分离，禁止失败后丢失恢复依据 |
| `MirrorMessage` / `binding_id` | 仅源/目标 chat/message 四字段加主键；未包含租户、账号、规则、版本、投递状态 | 新建完整映射表，不能靠原表直接承担多客户、多规则生产数据 |
| `config.py` | 导入时读环境和 YAML；`DirectionConfig` 与全局配置同文件；运行时按名字加载过滤器 | 先移出纯类型，再做实例化配置与过滤器白名单，避免不同账号串配置 |
| `_patch/sending.py` | 保留话题等发送适配，并调用 Telethon 内部行为 | 优先复用，但明确上游耦合；不宣称它是稳定公共 SDK |
| `main.py` 健康端点 | HTTP 返回 204，与账号实际连接状态无关 | 自建 liveness/readiness 与业务状态；启动成功不等于可发送 |

删除路径的两个问题属于本次静态阅读发现，尚未运行复现；实现时必须先用“两个目标部分失败、源与目标 ID 不同”的回归用例确认并修复。

### 4.2 保留、改造与不纳入

**优先保留：** 消息实体/格式处理、相册转换、关键词与 URL 过滤、来源格式、回复映射、话题映射，以及 copy/forward 发送的兼容逻辑。复用不代表把所有上游功能开放给客户。

**必要改造：**

1. 配置类型脱离导入副作用，构建 `RuntimeConfig`、`RuleSnapshot` 和过滤器注册白名单。
2. `EventHandlers → EventNormalizer → event_inbox`，不再直接发送。
3. 从 EventProcessor 提取 `ClonePlanner`；产出每目标的 `DeliveryPlan`，发送与落库交给新执行层。
4. `DeliveryExecutor` 封装新建、相册、编辑、删除、forward，返回结构化 `DeliveryResult` 或可分类错误。
5. 以 `MappingRepository` 和持久化表替换简单映射；必要时保留旧 `Database` 接口的兼容适配，但所有作用域由服务端绑定。
6. 统一 Clone、AI、补偿消息的发送入口，增加权限、停用、审批、租约与速率检查；不保留可绕过入口的旧事件发送回调。
7. 增加规则版本切换、排空、账号状态、错误分级、metrics 与控制命令消费者。

**不纳入：** 上游用于绕过“禁止保存/转发”的过滤器。仅注册经过审核的过滤器，源内容标记受保护时拒绝复制或转发；不提供规避限制的开关。设备/应用信息保持真实、稳定的客户端标识，不设计防风控伪装。

### 4.3 拟建接口与职责

以下是目标接口，不是现有 telemirror API：

```text
RuntimeConfigLoader.load(account_id, version) -> RuntimeConfig
EventNormalizer.normalize(telegram_event, account_scope) -> SourceEvent[]
ClonePlanner.plan(source_event, rule_snapshot, mapping_view) -> DeliveryPlan[]
MappingRepository.lookup_source(source_key, route_scope) -> MessageMap[]
DeliveryExecutor.execute(plan, attempt_context) -> DeliveryResult
SendPolicy.check(job, live_account, current_policy, approval) -> Decision
RuntimeController.apply(command) -> CommandResult
```

`DeliveryResult` 包含目标消息 ID 列表、逐条媒体对应关系、平台结果、状态、错误分类和是否结果未知。一次调用只负责一个目标路由；不在执行器内部再遍历所有目标。`SendPolicy` 同时用于 create/edit/delete，避免“新建停了，但编辑/删除还在执行”。

### 4.4 Fork 维护与许可证

- 建议维护独立 `telegram-runtime` 派生仓库，记录上游 remote、基线 SHA、补丁清单、回归用例、NOTICE 与 GPL 文本。
- 私有化分发修改后的 GPL 派生运行时时，应按 GPL 条件向接收方提供相应源码与构建所需材料。GPL 允许商业销售，不能把“商用”等同于“可以闭源分发派生程序”。
- 纯网络服务与交付二进制的义务触发不同；GPL-3.0 不是 AGPL。后台与 runtime 分进程有运维价值，**不自动证明它们法律上互不构成派生/组合程序**。
- 本架构可以继续设计和验证；正式分发前确认整体组合及交付义务。如果“全部代码保持闭源”是硬条件，需要重新确定授权或 Clone 实现路线，不能仅靠容器拆分承诺解决。

## 5. 账号登录、Session 与运行生命周期

### 5.1 登录过程

1. 操作员在所属项目创建账号，提交号码、Telegram 应用配置引用，申请短时登录事务。
2. Supervisor 分配登录 Worker；该 Worker 是此登录事务唯一客户端持有者，调用 Telethon 登录流程。HTTP API 只转交短时命令，不自行创建第二连接。
3. 网页分别提交验证码与必要的 2FA 密码；敏感内容不进入 URL、日志、审计详情、Celery payload 或持久化命令表。通过认证内网请求转发到登录 Worker；仅最小登录状态短时保留。
4. 登录成功验证 Telegram 用户 ID；在当前部署内检测重复绑定，避免同账号被重复导入多个 Worker。
5. Session 以信封加密存储，业务表只保存 `secret_ref`、密钥版本和状态；明文仅在所属 Worker 内存/受限临时挂载中出现。
6. 登录流程完成后销毁验证码、密码和挑战状态，审计只记录操作者、账号、结果和原因码。

### 5.1.1 Session 批量导入(协议号)

平台必须支持批量导入外部 Session(俗称协议号)。这是确定的业务能力，设计如下:

1. **导入包格式**：接受 zip 批次包，内含 `号码.session`(Telethon SQLite)+ `号码.json` 元数据配对；json 提供 `app_id/app_hash/device/app_version/twoFA` 等客户端指纹。后期可扩展 tdata、StringSession 格式，导入器按格式探测分发。
2. **校验 Worker 逐条验证**：解析格式 → 用包内 `app_id/app_hash/device` 指纹建客户端(**不得用平台默认指纹顶替，指纹不符是协议号最常见的封号触发点**)→ connect + `getMe` 最小验证 → 落结果。验证只读身份，不拉消息、不发言。
3. **验证结果分级**：`verified / auth_failed / 2fa_locked / spamblocked / deactivated`。`twoFA=true` 且密码未知的直接进 `2fa_locked`，可事后补密码重验；spamblock 来自 json 与 `getMe` 可见状态，如实展示不隐藏。
4. **来源追踪**：`telegram_account` 增加 `import_batch_id`、`import_source`(批次/供应商标注)、`imported_at`；`import_batch` 记录操作者、条目数、各结果计数、原始包 hash。导入即审计事件。
5. **去重与重绑**：按 `telegram_user_id` 在当前部署唯一；同号码重复导入默认拒绝，选择重绑时旧 Session 作废、需显式确认。
6. **隔离与节奏**：新导入账号进 `imported_quarantine` 状态，不自动加入 Clone 规则；验证按 IP/DC 限速错峰，避免同批次集中上线触发风控连锁。
7. **存储与保密**：导入的 `.session` 与号码按正常账号同等信封加密与脱敏规则；原始包在校验完毕、密文落库后销毁。UI 仍不提供明文导出。

合规边界由部署方与客户的授权关系承担：平台如实呈现 spamblock/twoFA 状态与验证结果，不做规避风控的伪装能力(客户端指纹沿用包内信息属"忠实还原"，不在禁止项内)。

### 5.2 状态模型

| 状态 | 含义与下一步 |
| --- | --- |
| `created / awaiting_code / awaiting_password` | 短时登录；超时回到需要登录，不能保持永久等待 |
| `ready / starting / online` | 凭据可用、Worker 启动、账号已授权且连接正常 |
| `degraded / reconnecting` | 有权限/网络/同步异常；区分接收、发送、AI 三类健康状态 |
| `flood_wait` | 保存服务器要求的恢复时间；所有相关发送按该范围暂停 |
| `paused / stopping / stopped` | 人工暂停、排空、已停止；默认暂停阻止新发送，任务保留 |
| `reauth_required / revoked / disabled` | 需要重新登录、Session 撤销或账号禁用；不循环重试敏感错误 |
| `imported_quarantine / validating` | 导入隔离待验证、校验进行中；隔离态不得加入规则或发送 |
| `2fa_locked / spamblocked` | 导入验证发现的锁定状态；补密码或解除后回到正常流转 |

账号状态不是一个布尔值：保存 `connection_state`、`auth_state`、`send_state`、`desired_state` 和最近原因；UI 展示合成结果及下一步操作。

### 5.3 独占归属与接管

- PostgreSQL `account_lease` 保存 `account_id / worker_id / generation / lease_until`，使用数据库时间、CAS 和递增 generation；Redis 不作唯一租约依据。
- Worker 每次领取和执行发送前验证账号归属及 generation；验证失败或 PostgreSQL 不可用时停止新发送。
- 参考起点：心跳 10 秒、租约 45 秒；这些值需压测与故障注入调整，不是安全保证本身。
- **Telegram 不识别平台 generation。** 旧进程在检查后停顿，恢复后仍可能发出已准备的请求；仅靠 Redis 锁、数据库租约或 Kubernetes Lease 无法严格隔离外部副作用。
- 首期只在 Supervisor 确认旧进程退出、旧节点已被隔离或旧会话已可靠失效后自动接管。无法确认时进入 `takeover_blocked`，通知人工处理，优先避免双发。
- 同账号升级使用 stop/drain/start，不能滚动重叠启动两个副本。登录与业务 Worker 同样服从这一所有权规则。

“停止”仅断开本平台连接；“撤销 Session”需要在界面明确其实际效果并验证撤销结果；删除数据库密文不等同于 Telegram 服务端撤销。

## 6. 数据模型、作用域与关键约束

### 6.1 通用规则

业务主键使用 UUID；Telegram chat/message ID 使用有符号 BIGINT，不能用 32 位整数。内部 `chat_id` 是 UUID，`telegram_chat_id` 才是平台 ID；HTTP 中 Telegram 大整数统一按字符串传输，避免 JavaScript 精度与后续范围问题。时间使用 UTC `timestamptz`。

每条客户业务记录具备 `tenant_id`，项目资源再包含 `project_id`。外键使用包含作用域的复合关联或等价数据库约束，不能只在 ORM 默认过滤条件中隔离。

### 6.2 实体清单

| 实体 / 表 | 核心字段或关系 | 主要约束 / 索引 |
| --- | --- | --- |
| `tenant, project, membership` | 客户、项目、用户角色与资源范围 | 成员唯一；资源查询必须匹配 membership |
| `telegram_account` | tenant/project、telegram_user_id、secret_ref、desired/observed 状态、import_batch_id/import_source/imported_at | 当前部署同 Telegram 身份默认唯一；移动项目走显式迁移 |
| `import_batch` | 操作者、包 hash、条目数、验证结果计数、来源标注 | 追加写；条目级验证结果挂到账号 |
| `account_lease, runtime_command` | worker/generation/租约；命令类型、payload、状态、去重键 | account 唯一；命令重放幂等，敏感验证码不入表 |
| `chat, account_chat, chat_authorization` | chat 平台身份；账号可见性/能力；客户授权依据、范围和失效时间 | 技术可访问性与业务授权分开验证 |
| `clone_rule, clone_rule_version, clone_target` | 账号、源 chat/topic、目标、模式、filters、版本、生效范围 | 规则版本不可变；目标路由 ID 稳定，删除目标只退役不复用 |
| `source_message` | source_scope、source chat/message、最新 revision、grouped_id、内容摘要、tombstone | `(tenant, project, source_scope, source_chat, source_message)` 唯一 |
| `event_inbox` | event_id、source_key、type、revision、payload_ref、ingest_seq、处理状态 | create/edit/delete 事件分别去重；扫描未处理状态索引 |
| `delivery_job` | kind、route_id、source_key/candidate_id、revision、account、payload_hash、rule_version、status、next_attempt_at | 每个业务动作幂等键唯一；按 account/status/due_time 索引 |
| `delivery_attempt` | job、attempt_no、worker_generation、request IDs、开始/结束、结果与原因码 | append-only；job + attempt_no 唯一 |
| `message_map` | 源 key、route、sender_account、目标 chat/topic/message、revision、删除状态 | 每源消息/路由/输出分片唯一；目标反查索引用于循环防护 |
| `album_group, album_item` | source_scope/grouped_id、成员、顺序、目标分组与分片 | 成员去重；每成员可追溯到目标 message |
| `agent, agent_binding, provider_config` | Agent 版本、群/话题绑定、模型配置引用、策略与预算 | 不把供应商密钥放在明文 JSON 配置 |
| `conversation, ai_run, ai_callback` | 隔离会话、上下文版本、请求状态、accepted ID、回调序列 | callback 按 bot/session/reply_to/sequence 去重 |
| `reply_candidate, approval` | 规范化内容、附件版本、hash、有效期、审批人/状态/版本 | approval 绑定不可变候选版本；发送任务唯一消费该候选 |
| `outbox, scheduled_job, media_asset` | 通知事件、到期任务、对象引用/校验/保留期限 | outbox 事务内写；scheduled occurrence 唯一 |
| `audit_event, policy_state` | 操作者/服务身份、对象、前后摘要、trace；开关 scope/version | 追加写审计；global/tenant/project/account 多层禁用优先 |

`source_scope` 必须显式建模：频道/超级群可用规范化 peer 作用域；普通小群等账号消息 ID 语义不同的场景加入接收账号身份。不要假设不同账号观察到的所有消息 ID 都可直接合并。第一阶段每条规则只有一个指定接收账号，减少歧义。

### 6.3 映射表的最小完整定义

```text
message_map
  id, tenant_id, project_id
  rule_id, route_id, rule_version_at_create
  source_scope, source_chat_id, source_message_id
  source_album_id?, source_member_index?
  sender_account_id
  target_chat_id, target_topic_id?, target_message_id
  output_part_index, last_applied_revision
  delivery_job_id, status, deleted_at?
  created_at, updated_at

UNIQUE(tenant_id, project_id, route_id, source_scope,
       source_chat_id, source_message_id, output_part_index)

INDEX(tenant_id, project_id, sender_account_id,
      target_chat_id, target_message_id)
```

同一源消息因两个合法规则向同一目标投递时，必须由路由语义明确允许或在发布规则时阻止；不能误靠唯一约束吞掉用户意图。`message_map` 不因一次删除失败而硬删除。

### 6.4 事务边界

1. 入站事务：更新 `source_message` revision + 写 `event_inbox`，提交后才进入处理。
2. 规划事务：锁定 inbox/source 状态，写每目标 `delivery_job` 和所需 outbox，标记已规划。崩溃可重扫，唯一键防止重复创建。
3. 领取事务：条件更新状态并写 attempt/租约，提交后再做网络调用；不能持有数据库事务等待 Telegram。
4. 结果事务：写目标映射、逐项结果、job 状态、审计摘要与通知 outbox，一起提交。
5. 审核事务：校验版本与有效期，更新审批并创建唯一发送任务；审批按钮重试不会重复创建任务。

外部发送位于第 3 与第 4 步之间，因此存在“已发送、结果未落库”的窗口，第 8 节定义其处理。

## 7. Clone 的完整处理流程

### 7.1 新消息

```text
Telegram update
  → 校验账号/群授权与源保护标志
  → 规范化、去重、源版本入库
  → 读取发布的规则快照
  → topic/关键词/媒体/来源过滤
  → 每个目标形成不可变投递计划
  → PostgreSQL delivery_job
  → 账号 Worker 领取
  → 最终权限/停用/审批/频率/归属检查
  → telemirror 发送适配
  → 保存目标映射与结果
```

计划中保存规范化后的文本/实体/附件版本或其不可变引用，重试不重新跑一遍可能已变化的规则。Clone 默认由已批准的规则授权发送；可配置消息级审核。AI 回复始终遵循 Agent 的审核策略。

### 7.2 copy 与 forward

- `copy`：使用账号新发一条内容，可配置来源说明，不冒充原作者；编辑/删除依据目标映射处理。
- `forward`：使用 Telegram 原生转发，保留其平台语义。上游编辑处理跳过 forward，因此首期界面禁用该模式的“内容编辑同步”；删除仍按映射和权限尽力执行。
- 不支持的消息类型、服务消息、投票、付费/受保护内容等返回明确 `unsupported` 或 `blocked` 状态。原生投票结构和测验结果不作为首期完整保真承诺。
- Telegram 对不同媒体的编辑能力不同；不能把“支持媒体消息”理解为任意媒体类型互换编辑。

### 7.3 相册与大媒体

- 复用 telemirror 的 Album 解析和相册发送；扩展持久化 `album_group/items`，避免重启丢掉聚合过程。
- 同账号、同源群、同 grouped_id 聚合；聚合窗口为可配置参数，初值参考上游约 1 秒，仅是起点。等待窗口结束后固化成员有序列表。
- 单条 NewMessage 的相册成员不能另发一次；晚到成员记录为可见异常，按规则采用补充发送或人工处理，不能静默丢弃。
- 返回的每个目标 message ID 与源成员逐项绑定；部分相册失败只处理缺失/不确定部分，不能重发整组造成重复。
- 同账号可复用合法媒体引用；引用过期时重新从授权源解析。下载/上传需要持久化暂存时使用私有对象存储与 TTL；不把大文件塞进 Redis、数据库 JSON 或 Celery payload。
- 文件大小、媒体类型、并发下载、项目存储配额均可配置；检查磁盘、内存与对象存储水位。AI 媒体链接限定用途、短时有效且不能读取其他项目对象。

### 7.4 编辑、删除与乱序

| 场景 | 处理策略 |
| --- | --- |
| create 尚未发送时出现 edit | 更新源最新版本；未开始的旧计划被新 revision 替代，发送最终内容；保留版本审计 |
| create 正在执行时出现 edit | 串行记录后续操作；create 确认后再执行最新编辑，不能并发编辑未知目标 |
| delete 先于 create 完成 | 写源 tombstone；取消未发送任务；在途任务若最终成功，创建目标删除任务 |
| 多次 edit 乱序 | 每源消息序列化处理；使用平台编辑时间/内容指纹形成 revision，拒绝旧版本覆盖；无法判序时重新读取授权源当前状态 |
| delete 后延迟到达 edit | tombstone 优先，忽略旧编辑；不要复活已删除源内容 |
| 部分目标删除失败 | 成功目标标 deleted；失败目标保留映射和重试状态；源/目标 ID 使用不同变量与字段 |
| 目标被手工删除 | 记录 target_missing；默认不自动重建，提供有权限的显式修复操作 |
| 无法编辑的媒体变化 | 标为 unsupported_edit；默认人工处理，不能静默删旧发新改变引用关系 |

Telethon 官方说明删除事件并非 100% 可靠，部分聊天场景缺少 chat 信息。无法从账号范围内已记录的源索引唯一定位时进入 `unresolved_delete`，**不扫描其他客户或按 ID 猜测删除目标**。定期抽查只能发现部分遗漏；访问失败/权限撤销不等于源已删除，不能据此批量删目标。

### 7.5 回复、话题、循环与规则变更

- 回复引用用 source reply ID 查同一路由目标映射；不存在时按规则选择普通发送或等待短时依赖，不无限阻塞。
- 话题 ID 是路由的一部分；目标话题关闭/删除后暂停对应目标，不自动发到其他话题。
- 发布规则时构建源→目标图，禁止自环和可确定的循环；runtime 反查本平台输出消息，默认不让 Clone 输出再次触发 Clone/AI。
- `source→target` 的反向镜像必须显式审核，初期直接不允许循环拓扑；仅靠内存缓存不够。
- 规则修改发布新版本；已入队任务保持原快照，除非用户选择显式取消。停用优先于快照，旧任务也不能继续发送。
- 已投递消息的编辑/删除按创建时规则版本和稳定 route_id 处理，并叠加当前授权与安全开关。退役路由仍保留映射及 cleanup 策略，不能硬删配置导致孤儿消息。
- 新源列表切换采用短时排空、处理器原子替换或受控重启，记录当前 `observed_config_version`；配置 API 成功不等于所有 Worker 已生效。

### 7.6 历史回填与断线补偿

首期至少实现有界断线补偿，不默认做全历史复制。保存每源游标及补偿时间窗，重连后在账号权限和速率限制内读取缺口；回填与实时事件共用 inbox 去重。历史消息批量回填可作为后续显式任务，配置时间范围、上限、预估量、暂停和进度。

StringSession 不能视为业务游标/未处理事件日志的替代品。即使库恢复更新，也需要应用级游标与去重；断线期间未观察到的删除无法保证完整重放，必须在状态页标记补偿范围和无法确认区间。

## 8. 任务队列、重试与一致性

### 8.1 双层异步机制

**Telegram 业务发送以 PostgreSQL 为准。** `delivery_job` 存全部待发动作，账号 Worker 使用按账号过滤的行锁/条件更新领取；同账号初期一个发送执行槽，同一源消息的后续操作按依赖顺序执行。被阻塞的目标不应长期占住其他无关目标的执行槽。

**Celery/Redis 用于有限辅助任务。** 创建 `ai_run`、媒体分析或通知任务时，同时写 outbox；dispatcher 将 job ID 投递给 broker。允许通知重复，消费者必须读取数据库状态并幂等执行。周期扫描超时/未完成业务记录重新唤醒，解决通知发布后 Redis 丢数据的问题。

Celery task ID 和 Redis Pub/Sub 都不能代替业务幂等键。长期 FloodWait 写 `next_attempt_at` 并释放执行槽，不在 Celery 或账号事件循环里长时间 sleep。

### 8.2 投递状态

```text
pending → waiting_approval / ready
ready → leased → sending → succeeded
                     ├── retry_wait → ready
                     ├── blocked
                     ├── failed_permanent / dead_letter
                     └── uncertain → reconciled_succeeded
                                  → confirmed_not_sent → ready
                                  → manual_review
任意未发送状态 → cancelled / expired / superseded
```

`blocked` 表示当前权限、开关或依赖条件阻塞，条件恢复后重新验证；`dead_letter` 表示重试耗尽，需要显式操作。`sending` 的 Worker 消失后先进入 `uncertain`，不能直接改回 ready。后台列表必须显示每个目标状态，而不是只显示整条源消息“成功/失败”。

### 8.3 错误分类

| 错误 | 默认动作 |
| --- | --- |
| Telegram FloodWait / slow mode | 依据服务器等待时间持久化暂停范围；不轮换账号规避限制 |
| 明确未发送的临时网络/服务错误 | 指数退避加抖动、上限次数；再次执行全部发送检查 |
| 请求可能已被服务器接受但回执丢失 | uncertain；保留请求标识与内容，不盲目重新发送 |
| Session 失效、账号封禁/停用 | 停止该账号相关任务，要求人工恢复或重新登录 |
| 目标无权限、话题失效、源保护 | 阻塞路由并提示具体原因；不无限重试 |
| 内容不合法/类型不支持 | 永久失败；允许修正配置后创建新的显式重处理任务 |
| 数据库不可用 | 停止新发送；已在途结果保留为需核查，恢复后处理 uncertain |
| Redis 不可用 | 暂停依赖 Redis 的 AI/有限任务；发送若无法完成频控则默认阻塞，不以缓存失效放行 |

应用与 Telethon 内部自动重试/自动 FloodWait 等待要统一配置，避免叠加重试和长时间阻塞；具体参数以固定 Telethon 版本行为验证后确定。

### 8.4 结果不确定与去重边界

数据库唯一键只防止本地重复计划。Telegram 发送与数据库提交不在同一事务，不能实现通用端到端 exactly-once。

改造发送适配时，可对支持的 MTProto 请求保存并复用稳定 `random_id`，并对相册每项分别记录；**这是待验证的增强，不是已具备的可靠性保证**。上游高层发送不会自动把应用任务的持久化标识关联到所有重试。

请求回执不明时优先用已知平台返回、请求关联信息和有限目标历史核查。内容相同不能单独证明是同一任务；无法证明时保留 uncertain，让操作员确认或明确接受可能重复的重新投递。编辑/删除通常更容易幂等恢复，但仍要区分“不存在”“无权限”和“请求未完成”。

### 8.5 全局停用的真实语义

- `policy_state` 支持全平台、租户、项目、账号、Agent、规则开关；任一禁止优先。
- 发送前读取当前策略版本，禁止只在入队时检查；关键开关以数据库为准，缓存仅加速。
- 停用响应先返回 `requested` 和 epoch，各 Worker 确认后显示 `effective`、未确认 Worker 和在途数量；不能把 HTTP 200 当成所有进程已停止。
- 已交给 Telegram 的在途请求无法撤回。界面明确“阻止尚未开始的副作用”，若要处理已发消息需另行授权删除任务；完全停用时删除本身也不得偷偷执行。
- 失联 Worker 的紧急处置是终止/隔离进程或节点、必要时撤销会话。多账号系统不存在仅靠广播就保证绝对即时停发的方案。

### 8.6 频率、黑白名单与公平调度

- 群和账号必须先在业务授权名单内；黑名单优先于白名单。按租户、项目、群、话题、发送者和 Agent 设置作用域，服务端统一解释冲突，不让前端各自决定。
- Telegram 发送限制按账号、目标群和业务类型分层，AI 再加会话冷却与日预算；最终允许速率取所有适用限制中最严格的结果。配置值是平台保护上限，不代表 Telegram 官方额度。
- Redis 原子操作维护 token bucket/短窗计数，数据库保存策略、长期配额及 FloodWait 到期；Redis 状态丢失后保守初始化并从持久化尝试记录恢复必要水位，不以空桶记录缺失作为无限额度。
- Worker 不把一次速率通过当成长期许可：临近网络请求时再次检查是否到期、停用或进入平台等待。重试、编辑、删除、媒体分段同样纳入适用限制。
- 同账号任务按项目/目标进行公平轮转，保留同源消息因果顺序；有界积压超过阈值时延迟回填、合并尚未执行的旧编辑、拒绝额外非关键生成，不静默丢弃已接收任务。

## 9. AI 群聊与 LangBot 集成

### 9.1 采用已存在的 HTTP Bot 接口

进一步核实发现，当前 LangBot 提供 **HTTP Bot Adapter**，有签名入站、异步回调、session_id、分段回复和 reset，可避免从零编写 Telegram 平台适配器。

本方案使用其现有 `POST /bots/{bot_uuid}`，返回 202 后等待签名回调；默认不用阻塞 `/sync`。FBA AI Gateway 把 Telegram 事件转换成 HTTP Bot message chain，把回调转换为 `reply_candidate`，不把回调原样转发到 Telegram。

该接口与 LangBot 的 Telegram Bot Token 接入是两条独立路径；这里只配置 HTTP Bot，不让 LangBot 持有用户账号 Session。

### 9.2 完整 AI 流程

```text
授权群消息
  → 排除自身/平台输出/黑名单/过期消息
  → 检查显式触发、Agent 启用、冷却与预算
  → 冻结 source revision、Agent version、context version
  → ai_run + outbox
  → Celery 发签名 HTTP Bot 请求
  → LangBot pipeline → 模型供应商
  → 签名回调持久化并快速响应
  → 聚合完整回复、验证内容、产生不可变候选
  → 人工审核 / 已批准策略的自动审核
  → 同一个 PostgreSQL delivery_job
  → 账号 Worker 最终校验并发送
  → 实际发送结果回写 conversation 与审计
```

首期默认关闭自动回复、工具执行与任意第三方插件，仅支持提及/前缀/指定触发的候选生成。后续开放规则自动回复时仍需频控、授权群白名单、明确 AI 身份、配额和全局停用。

### 9.3 上下文、并发与关联

会话键使用服务端生成的稳定不透明标识，其逻辑包含：

```text
tenant + project + chat + topic + agent + context_epoch
```

- 每会话先限制一个生成中的 `ai_run`，新触发排队或合并；合并必须在平台侧记录来源消息集合。
- 首期关闭 LangBot 自动聚合，避免多条入站被合并后无法把 callback 精确关联到一个审批对象。
- 记录 LangBot `accepted_message_id`；回调通过 bot/session/reply_to/sequence 关联；即使回调早于 202 响应落库，也先持久化等待关联，不丢弃。
- 候选只有收到 final 且已收到序号连续、内容校验通过的分段后才可审核；缺段或超时进入 `incomplete`，不把半截回复发群。
- 原消息被编辑/删除、Agent 或上下文版本变化后，尚未发送的候选作废或重生成，不能继续发送陈旧审批结果。

### 9.4 避免“模型以为自己已说过”的上下文错误

LangBot 可能在 pipeline 中把生成回复写入历史，但候选可能被拒绝或发送失败。平台 `conversation` 的真实已发送记录必须独立于模型内部历史。

首期采取保守策略：候选等待审批/发送时锁住该会话的下一次生成；拒绝、超时或失败后标记 LangBot 历史需重建，使用 reset 或新的 `context_epoch`，从平台记录的最近已发送对话重建有界上下文。重建不是伪造多条 HTTP Bot 入站去触发多次回复，应由受控 pipeline/context bridge 一次注入。

这一 context bridge 属于必要适配工作；不能只拼一个 session_id 就宣称历史完全一致。统一控制最近消息数、token 上限、摘要版本、保留天数和重建规则。

### 9.5 回调可靠性与模型预算

- 使用 HTTP Bot 官方 HMAC-SHA256 方案，校验原始 body、时间窗和签名；服务端 bot 绑定决定租户，不信任消息自带 scope。
- 本地 `ai_callback` 唯一键防重放和重复处理；落库后才返回 2xx，数据库暂不可用返回可重试错误。
- 源码显示 HTTP Bot 回调使用内存队列，有容量上限与有限重试；不能把它当成可靠消息队列。平台设置 `ai_run` 截止时间，缺失回调显示失败/不完整。
- 生产增强优先在 LangBot 适配层补 durable outbox 与发送确认；若首期暂不补，必须接受“生成可能完成但候选未到达”的可见失败，不能自动把重新生成当成同一结果。
- 入站 Idempotency-Key 不替代平台持久化 ai_run；遇到 409 不能在缺少关联信息时直接标成功。模型请求结果不明时不要盲目重发造成重复费用。
- 预留最大 token/费用预算，结算实际可得用量，超时与回调缺失标记待核账；预算按租户、项目、Agent、日/月统计。

### 9.6 统一引擎接口与模型供应商

平台先定义 `AIEngineAdapter.submit / cancel_local / get_status / reset_context`；首个实现是 `LangBotEngineAdapter`。`cancel_local` 仅阻止回调进入发送，不承诺远端推理一定停止。

供应商统一由 LangBot model/provider 层复用，平台保存 provider/model 的受控引用和能力约束，首期只启用一个已验证供应商。第二阶段再做多供应商切换、费用、配额、错误映射；切换前检查数据处理区域、上下文能力和预算，不能因一个供应商报错就无条件把客户内容发送给另一个。

## 10. 审核、权限与客户隔离

### 10.1 审批必须绑定实际发送内容

候选记录包括文本、消息实体、附件对象版本/校验值、目标群/话题、账号、reply target、Agent/规则版本、内容 hash 和过期时间。渲染、切分及媒体校验应在审批前完成；审批后不能静默重新生成、修改目标或替换附件。

审核 API 使用版本检查，允许 approve/reject/edit-and-resubmit。内容有任何变化产生新版本，旧审批失效。Worker 发送前再次验证审批状态、内容 hash、有效期、账号/目标权限及全局开关。

分段发送的每一段均属于同一个已批准候选及固定 part index；每段都检查停用。部分发送失败不重新发送已成功的段。审核者撤销与发送同时发生时，要展示可能在途的事实，不能承诺撤销已发出的请求。

### 10.2 角色矩阵

| 操作 | 客户管理员 | 项目操作员 | 审核员 | 审计只读 |
| --- | --- | --- | --- | --- |
| 用户/角色与项目授权 | 是 | 否 | 否 | 只读授权范围 |
| 账号登录、撤销 | 单独敏感权限 | 可授予 | 否 | 仅看脱敏状态 |
| 群授权、Clone/Agent 配置 | 是 | 项目范围 | 只读 | 只读 |
| 审批候选回复 | 可授予 | 默认不能审核自己提交的内容 | 项目范围 | 只读 |
| 重试/取消/暂停任务 | 是 | 项目范围 | 仅审核相关操作 | 否 |
| 紧急停用 | 是 | 可授予项目停用 | 可授予项目停用 | 否 |
| 恢复全局发送、密钥管理、导出 | 单独高权限、二次确认 | 否 | 否 | 否 |

平台运维管理员与客户管理员分开；运维不默认拥有客户消息正文读取权限，特殊访问走授权和审计。RBAC 只解决“能做什么”，每条数据还需要资源归属检查。

### 10.3 隔离必须贯穿所有路径

- 数据库：tenant/project 条件、复合外键；共享 SaaS 前增加非超级用户 RLS 防御并测试连接池 scope 清理，不能用表 owner 绕过策略。
- 队列：任务 ID 解析后再查归属；Worker 只能处理绑定账号和项目的数据；跨租户 ID 替换必须返回拒绝。
- Redis：key 含作用域，broker 与业务缓存分逻辑职责；不要把 key 前缀当安全隔离本身。
- 对象存储：私有 bucket/prefix、授权下载、短时签名、服务端 key 生成；防目录遍历与跨项目引用。
- AI：每客户独立实例起步；共享部署前检验 bot、provider credential、pipeline、context、插件和知识库隔离，不只检查 conversation 表。
- 日志/监控：用户看的是过滤后的业务日志；基础设施原始日志和全局 metrics 不开放给客户。

## 11. Web 页面与 API 设计

### 11.1 页面

| 页面 | 必须显示与允许操作 |
| --- | --- |
| 概览 | 在线账号、积压、最老任务、投递成功/失败/不确定、待审数量、全局停用状态 |
| 账号 | 登录步骤、脱敏号码、Telegram ID、归属 Worker、授权状态、FloodWait 到期、暂停/停止/撤销 |
| 群/频道 | 账号可见目录、源/目标能力、授权依据、话题、同步时间；技术可见不等于已授权 |
| Clone 规则 | 单账号、源/目标、copy/forward、filters、编辑/删除能力、dry-run、发布版本与 Worker 生效版本 |
| 投递记录 | 源→每目标映射、所有尝试、失败原因、uncertain、受控重试/取消 |
| Agent | 模型引用、触发策略、上下文、冷却、白名单、预算、审核方式、身份说明 |
| 审核 | 完整候选预览、来源上下文、目标、版本、有效期、批准/拒绝/修改重审 |
| 审计与运维 | 配置变更、发送/审核轨迹、停用确认、备份恢复状态、告警 |

第一阶段用游标分页与短轮询即可。第二阶段 WebSocket 仅推送经过鉴权、过滤的业务事件；断线后以持久化游标拉取缺口，不能依赖 Pub/Sub 保存历史。

### 11.2 对外 API（拟建）

路径以 `/api/v1/projects/{project_id}` 为前缀，省略号不代表真实已存在接口。

| 方法 / 路径 | 用途 | 关键约束 |
| --- | --- | --- |
| `POST /accounts` | 创建账号元数据 | 验证项目角色；返回账号 ID |
| `POST /accounts/import` | 批量导入 Session 包(zip) | multipart;返回 batch_id；逐条异步验证 |
| `GET /imports/{batch_id}` | 导入批次状态 | 条目级验证结果与原因码 |
| `POST /accounts/{id}/login/start` | 创建登录事务 | 202 + challenge_id；号码脱敏 |
| `POST /login-challenges/{id}/code`、`/password` | 提交验证码 / 2FA | 短时、限次、不可记录 body |
| `POST /accounts/{id}/start`、`/pause`、`/stop`、`/revoke` | 生命周期 | 异步 command_id；revoke 二次确认 |
| `POST /accounts/{id}/chats/sync` | 同步群和能力 | 创建账号 Worker 命令 |
| `GET /chats`、`/chats/{id}/topics` | 目录 | 按账号权限和业务授权过滤 |
| `POST /clone-rules`、`PATCH /clone-rules/{id}` | 创建/修改草稿 | 乐观锁版本；校验循环与账号权限 |
| `POST /clone-rules/{id}/dry-run`、`/publish` | 预览/发布 | dry-run 无 Telegram 副作用；publish 返回 config version |
| `GET /deliveries`、`/deliveries/{id}` | 每目标状态与映射 | 游标分页；正文按权限脱敏 |
| `POST /deliveries/{id}/retry`、`/cancel` | 任务控制 | uncertain 不能走普通重试，需单独决策流程 |
| `POST /agents`、`PATCH /agents/{id}` | Agent 配置 | 模型配置引用，禁止任意代码/plugin URL |
| `GET /approvals`；`POST /approvals/{id}/approve`、`/reject` | 审批 | expected_version、内容 hash、有效期和审核权限 |
| `POST /policies/pause`、`/resume` | 项目停用/恢复 | 返回 epoch 与确认状态；恢复是单独权限 |
| `GET /commands/{id}`、`/audit-events` | 异步结果 / 审计 | 不返回秘密或其他项目记录 |

全局开关放在管理员专属路由；模型密钥只写接口返回掩码，不读取明文。对创建、发布、审批、重试等使用 `Idempotency-Key`；更新使用版本号/If-Match。响应包含 `request_id`、结构化 error code，不向前端暴露库堆栈。

### 11.3 内部协议（拟建）

`runtime_command` 类型包括 `StartAccount`、`StopAccount`、`ReloadConfig`、`SyncChats`、`ReconcileSource`、`CancelJob`；统一包含 command_id、scope、account_id、expected_generation、deadline 和 trace_id。Telegram 执行命令只能在账号 Worker 内完成。

`POST /internal/ai/langbot/{binding_id}/callback` 是平台拟建回调地址；binding_id 决定 bot/租户/密钥，正文仅作为输入校验。LangBot 侧沿用其真实 `/bots/{bot_uuid}` 协议。

所有跨进程事件包含 `schema_version`。业务消息对象序列化为受验证 JSON 和对象引用，不通过 broker 传 Python pickle 或直接序列化 Telethon 内部对象。

## 12. 配置、定时任务与审计

### 12.1 配置样例（目标领域模型，非原版 telemirror YAML）

```yaml
rule:
  id: rule_001
  version: 3
  account_id: account_001
  source:
    chat_id: chat_source
    topic_id: null
  targets:
    - route_id: route_001
      chat_id: chat_target
      topic_id: null
  mode: copy
  sync_edit: true
  sync_delete: true
  approval_policy: rule_authorized
  filters:
    - type: keyword_allow
      values: ["公告", "更新"]
    - type: source_attribution
      enabled: true
  policy:
    reject_protected_content: true
    ignore_platform_outputs: true
    on_missing_reply: send_without_reply
```

不向客户开放原始 Python 类名或 YAML 构造器。后台把类型化配置编译成已注册过滤器实例；Regex 限制长度、复杂度与执行时间，避免阻塞账号事件循环。

### 12.2 调度

首期调度用于群目录刷新、补偿、清理、metrics 汇总与备份提醒。单活 scheduler 以 PostgreSQL `scheduled_job` 为依据，`(job_id, scheduled_at)` 唯一，避免多实例重复触发。用户定时消息在第二阶段进入同一个投递/审批流程，记录 IANA 时区与 DST 策略，不调用 Telegram 直接绕过平台队列。

### 12.3 审计

审计事件区分用户操作、系统决策、外部调用结果：记录 actor、scope、action、resource、request/trace、前后配置摘要、审批版本、结果与原因。Session、OTP、2FA、API key、私密 URL 查询参数均不能入日志。消息正文默认不进入通用日志；必要业务正文单独存储、限权和设置保留期。

业务状态与审计摘要尽可能同事务写入；操作日志与投递历史不是同一张表。备份/外部审计归档保护长期追踪，避免业务清理把失败证据一起删掉。

## 13. 生产部署、安全与密钥

### 13.1 首期 Docker Compose 拓扑

```text
edge network:
  reverse-proxy :443 → web / control-api

private application network:
  control-api / supervisor / dispatcher / scheduler
  task-worker / telegram-runtime-account-*
  langbot (+ 按锁定配置所需的 plugin runtime)

private data network:
  PostgreSQL / Redis / private object storage

ops network:
  metrics collector / dashboards / log collector
```

公网只开放 HTTPS；数据库、Redis、LangBot 管理面板、Worker 控制接口和 metrics 不映射公网端口。应用进程非 root、只读根文件系统（允许指定暂存目录）、最小 capability、资源限制、健康检查、优雅退出和日志轮转。

私有化首期由部署人员生成固定账号 Worker 服务或配置，Supervisor 通过受限进程/编排代理启停它们。**不能把宿主 Docker socket 挂到公网 FBA API**。动态容器编排应由独立受限控制服务承担；服务只接收预定义账号操作，不能执行任意镜像或 shell 命令。

LangBot 是否需要 plugin runtime 依据固定版本启动配置验证；禁用插件/工具功能不等于可以猜测删掉其必要运行组件。Box、任意 shell、MCP 工具不作为首期能力开放。

### 13.2 密钥与网络

- Session、Telegram api_hash、模型密钥、HMAC secret、数据库密码分别管理，使用 KMS/Vault 或客户密钥系统；数据库备份与解密密钥分开保存。
- 密钥服务身份限定租户/账号；Worker 仅能解密自己的 Session。密钥版本可轮换，轮换期间有明确兼容窗口。
- 使用环境注入或受控 secret mount，不把秘密写进镜像、git、任务 payload 或 Compose 仓库样例。
- UI 使用安全 Cookie/CSRF 防护或一致的 token 策略；敏感操作重新认证，组织 SSO/MFA 可作为接入项。
- 仅允许必要外联：Telegram、配置过的模型端点、对象存储与运维服务；用户自定义模型端点/回调需受控，防 SSRF、内网探测和凭据泄露。
- 模型输入是非可信群内容，不能改变系统策略；工具执行权限由平台策略控制，不能由提示词自行提升。

### 13.3 多实例与高可用演进

API 可以水平扩展，状态放数据库；Celery worker 按负载扩展；PostgreSQL 使用托管 HA 或明确主备策略。Telegram runtime 按不同账号分片扩展，不能以同账号多副本增加吞吐。Supervisor/scheduler 可多实例部署但单 leader，接管规则仍需旧 Worker 隔离。

共享 SaaS 之前单独评审 RLS、资源配额、密钥分区、LangBot 隔离和运维访问；不把“有 tenant_id”当成多租户上线验收。

## 14. 可观测性、容量与目标

### 14.1 必须有的业务指标

- 每账号连接/授权/发送状态、心跳时间、config version、generation、重连次数与 FloodWait 到期。
- 入站速率、每目标成功/失败/blocked/uncertain、待发数量、最老任务年龄、按原因分类的重试和死信。
- 相册不完整、映射缺失、未定位删除、断线补偿区间、在途请求与停用未确认 Worker。
- AI 等待/生成/缺失回调、候选拒绝率、待审年龄、实际发送率、token/费用与预算余额。
- PostgreSQL 连接/延迟、Redis 容量、对象存储和本地暂存空间、CPU/内存及错误事件。

metrics 标签限制基数：原始 message ID、手机号、用户文本不能成为标签；账号级明细按部署规模决定放日志/业务表或有限指标。trace 关联 source event → job → attempt → Telegram result，AI 则关联 ai_run → callback → candidate → approval → job。

### 14.2 容量估算

输入变量至少包括账号数 A、每账号源消息速率 λ、平均目标数 F、媒体占比 M、媒体大小 S、保留期 D。粗估投递量为 `A × λ × F`；媒体下载量取决于复用/暂存策略，上传量取决于目标数和引用可用性；消息表、attempt、映射和审计增长都需计入，不能只按源消息行数算容量。

资源按实测扩容；不提供“一个账号每秒固定可发多少条”的平台承诺。账号队列最老任务持续增大时先检查权限/FloodWait、目标扩散和媒体体积，再减少范围、限流或延后任务，不能靠账号轮换规避限制。

### 14.3 初始验收目标（待客户确认）

| 指标 | 建议起点 | 测量范围 |
| --- | --- | --- |
| 控制面可用性 | 月度 99.5% 起评 | 只针对自有管理 API；不包含 Telegram/模型供应商可用性承诺 |
| 文本 Clone 延迟 | 在约定负载、无排队/平台等待时 P95 ≤ 5 秒 | 平台收到事件到确认目标结果；不适用于大媒体和人工审核 |
| 异常可见性 | 心跳异常 ≤ 60 秒提示；所有失败可查询 | 接管耗时另外统计，不能为达成指标冒险双活 |
| 灾难恢复 | RPO ≤ 15 分钟、RTO ≤ 2 小时作为预算目标 | 依赖 WAL/备份/密钥与演练；恢复后未知投递需核查 |
| 正确性 | 已落库任务无静默丢弃；跨租户访问测试全拒绝 | 不等于上游所有事件都一定可观测，也不保证恰好一次 |

负载规模由客户填写再压测；未确定前这些数值不能写入对外 SLA。Telegram 端已发出的副作用不能通过数据库备份回滚，RPO 也不能解释为消息行为自动回退。

## 15. 备份、恢复、升级与回滚

### 15.1 备份

- PostgreSQL 定期全量 + WAL/PITR，覆盖业务库与 LangBot 库；备份加密、异地/独立故障域存储并校验。
- 对象存储配置版本/生命周期；Session 密文、账号绑定与密钥版本一起纳入恢复清单，但解密密钥独立保护。
- Redis 可开启 AOF 以减少恢复成本，但数据库任务才是重建依据；不能只备份 Redis。
- 记录备份清单、时间点、镜像摘要、迁移版本、规则版本与密钥版本。保留期按客户数据政策确定，消息正文默认最小化。

### 15.2 恢复顺序

1. 隔离旧环境，确认旧账号 Worker 已停止；新环境默认全局停用。
2. 恢复 PostgreSQL、对象存储、LangBot 状态与密钥引用；验证权限与数据范围。
3. 重建缓存和 outbox 通知；把恢复时间点之后或结果不明的 sending 任务标记待核查。
4. 验证 Session 是否仍有效，恢复群权限和源游标；恢复旧数据库可能遗漏已发消息，因此不能直接批量重放。
5. 核查 uncertain，执行有界同步；分账号启用只接收/预览，再经确认恢复发送。
6. 记录实际 RPO/RTO 和未覆盖区间；至少在上线前做一次隔离环境恢复演练。

### 15.3 发布与回滚

CI 产出固定镜像，执行单元/集成/隔离测试和依赖扫描；数据库采用 expand/contract，迁移在单独一次性任务中运行。先停止新投递、排空在途，再升级单账号 Worker；多账号分批。

代码回滚要求旧版本兼容新 schema 与任务 schema_version；不通过删除数据库字段或退回备份“回滚已发送消息”。上游更新以明确版本合并，不自动追随 main；升级 Telethon/LangBot 后重跑相关协议与错误场景测试。

## 16. 仓库组织与代码边界

建议两个主要代码仓库加固定版本外部依赖。以下为目标目录，不代表已创建：

```text
telegram-platform/
  backend/                      # 基于 FBA
    app/telegram_accounts/      # 账号元数据、登录事务、命令 API
    app/chats/                  # 可见目录、授权、话题
    app/clone_rules/            # 配置草稿、版本、dry-run、发布
    app/deliveries/             # 查询、重试、uncertain 处理
    app/agents/                 # Agent、预算、上下文编排
    app/ai_gateway/             # LangBot 入站适配与回调接收
    app/approvals/              # 审批状态机与候选固化
    app/policies/               # 停用、黑白名单、速率策略
    app/audit/                  # 业务审计
    jobs/                       # dispatcher、scheduler、Celery
  web/                          # FBA 配套 UI 的业务页面
  contracts/                    # HTTP OpenAPI、事件 JSON Schema
  deploy/                       # 镜像编排、监控、备份部署说明
  tests/                        # API、跨租户、集成、故障注入

telegram-runtime/               # telemirror GPL 派生仓库
  telemirror/                   # 保留上游核心与必要补丁
  runtime/
    account/                    # 单客户端与所有权、生命周期
    ingest/                     # 事件规范化、相册、补偿
    planner/                    # 规则编译与逐目标计划
    delivery/                   # 队列、发送策略与结果
    storage/                    # 完整映射/任务仓储
    control/                    # 命令消费者与健康/metrics
  tests/                        # 上游兼容、映射、发送、失败恢复
  UPSTREAM.md                   # 基线 SHA、补丁和升级记录
  LICENSE / NOTICE

外部固定依赖：
  LangBot 镜像/必要适配 fork
  FBA/FBA UI 基线提交与锁文件
```

避免为复用少量类型把 GPL Python 包导入 FBA。跨服务以审定的 HTTP/JSON 契约交互；协议和共享代码的许可归属也需明确。目录名可以随实际 FBA 模块约定调整，职责不变。

## 17. 开发批次与可验收交付

以我可执行的工程批次估计，实施可拆为约 **6–9 个开发会话**，再加外部账号授权、供应商开通、许可证确认、客户验收和持续运行观察。不是完整生产交付的固定时长承诺；并发量和 UI 深度会改变拆分。

| 批次 | 开发内容 | 退出条件 |
| --- | --- | --- |
| 0：版本与授权基线 | 固定 telemirror/FBA/LangBot；确定交付许可证、测试账号与群；创建派生仓库 | 能构建镜像；账号同时具备源读/目标写；许可证路线可执行 |
| 1：账号与事件基础 | FBA 身份/项目、登录事务、Session 加密、一个账号一个 Worker、事件落库 | 两账号独立在线；重启不串 Session；未授权群拒绝 |
| 2：可靠 Clone | Planner/Executor、完整映射、文本媒体相册、目标独立任务、删除修复 | 一源两目标；一目标失败不影响另一目标；编辑/删除可追踪 |
| 3：生命周期与后台 | 规则版本、dry-run、队列状态、重试、uncertain、租约/排空/补偿 | 重启/断网可恢复；不能盲重发未知任务；旧进程未隔离不能接管 |
| 4：AI 与审批 | HTTP Bot、回调去重、上下文桥接、候选固化、人工审核、统一发送 | 拒绝不发、过期不发、修改重审；LangBot 无直接 Telegram 发送权 |
| 5：生产封装 | RBAC 全路径、metrics、告警、备份恢复、发布回滚、运行手册 | 灾难恢复演练、故障注入与约定规模持续运行通过 |
| 6：第二阶段 | 共享租户/项目、模板、多供应商、调度 UI、实时日志、统计 | 独立多租户隔离和容量验收后逐项启用 |

不把账号数量扩张放在可靠性之前。每一批次交付代码、迁移、接口契约、自动化测试与操作文档；功能未经过约定验收不标记“生产可用”。

## 18. 测试矩阵与上线门槛

| 测试面 | 必测场景 | 通过标准 |
| --- | --- | --- |
| Clone 基础 | 文本/实体、图片、视频、文件、相册、话题、回复、一源多目标、copy/forward | 映射完整，格式符合约定；forward 编辑能力在 UI 明示 |
| 编辑/删除 | 多次编辑、删除先到、部分目标失败、源/目标 ID 不同、手工删目标 | 不误删其他源/目标；失败映射保留，tombstone 不被旧 edit 复活 |
| 去重/崩溃 | 重复事件、领取后崩溃、发送后落库前崩溃、相册部分回执 | 无本地重复任务；不确定任务不自动重发整条/整相册 |
| 账号所有权 | 两 Worker 竞争、进程停顿恢复、租约失效、节点失联、升级 | 停止新副作用；无法确认旧实例退出时拒绝接管 |
| 上游限制 | FloodWait、Session 撤销、权限变化、受保护内容、话题关闭 | 按服务器等待，明确阻塞，无账号轮换/限制绕过 |
| 数据库/Redis | PostgreSQL 故障、Redis 重启/丢队列、对象存储失败 | 不静默丢任务；Redis 通知可重建；不可验证策略时不发送 |
| AI 协议 | 202 前回调、乱序/重复/缺段、签名错误、过期、409、回调进程重启 | 只接收合法完整候选；不把缺失回调当成功，不重复发送 |
| 审批 | 同时批准/拒绝、内容或附件替换、原消息变化、过期、停用与在途 | 内容版本一致；未开始任务停发；在途状态明确 |
| 上下文 | 不同客户/群/话题/Agent、拒绝候选、发送失败后下一轮 | 无泄漏；模型历史不把未发候选当成真实已发消息 |
| 权限 | 改 URL/对象 ID/任务 scope/附件 key；审计导出；日志订阅 | 全链路资源拒绝，不只前端隐藏按钮 |
| 容量与恢复 | 目标扩散、媒体堆积、长期运行、备份恢复、版本回滚 | 达到约定负载目标；恢复默认停用，未知副作用先核查 |

先用 Fake Telegram Transport 与固定事件集验证状态机和错误路径，再用客户授权的测试账号/群验证真实平台语义。不能为了测试主动压平台到限流；FloodWait/节点失败等采用模拟与故障注入。

上线硬门槛：关键路径自动化通过、真实测试群矩阵通过、无跨客户数据访问、所有副作用经过统一发送检查、Session 不入日志、备份可恢复、停用/未知结果/值班处理有可执行手册。持续运行观察长度按客户要求约定，建议首轮至少覆盖 72 小时及一次重启恢复。

## 19. 需求映射与待确认参数

### 19.1 原始需求覆盖

| 需求组 | 架构位置 |
| --- | --- |
| Userbot 登录、Session、多账号、群同步、状态监控 | 第 5、6、11、14 节 |
| 一对多 Clone、媒体、编辑删除、规则 | 第 4、6、7、8 节 |
| AI Agent、上下文、策略、统一供应商接口 | 第 9、10 节 |
| Web Dashboard、角色权限、操作日志 | 第 10、11、12 节 |
| 队列、Redis、PostgreSQL、Docker、监控恢复 | 第 6、8、13、14、15 节 |
| 多租户/项目、模板、多供应商、定时、实时日志、统计 | 第 1、9、10、11、12、17 节；第二阶段专门验收 |
| 人工审核、频控、黑白名单、全局停用 | 第 8、9、10 节；第一阶段即生效 |
| 备份与恢复 | 第 15 节；基础能力首期，租户自助界面二期 |

### 19.2 实施前填写，不阻塞本次架构交付

| 参数 | 本方案默认 / 待确认 |
| --- | --- |
| 交付模式及 GPL | 默认维护 GPL runtime fork；确认客户接受对应源码交付及组合许可边界 |
| 首期规模 | 账号数量、群数量、源消息峰值、平均目标数、媒体比例/大小待填写 |
| 部署 | 默认单客户私有化；客户云/本地网络、出口、区域和密钥服务待确认 |
| Clone 语义 | 同账号收发；copy 默认；forward 不编辑；默认不自动重建手工删除目标 |
| AI | 一个供应商、显式触发、人工审核；模型名称、预算、数据区域与保留期待确认 |
| 消息保留 | 正文、映射、审计、媒体和备份分别确定期限；映射寿命影响后续编辑/删除能力 |
| 可靠性 | 第 14 节目标需确认；能否接受 uncertain 人工核查和删除事件的上游限制 |
| 账号与群授权 | 测试/生产账号所有者、授权群清单、管理权限证明与撤销流程待确认 |

## 20. 源码与官方文档依据

本架构的关键依据固定到调研提交，便于实施时对比版本变化：

1. [telemirror 核心：EventProcessor / EventHandlers / Mirroring / Telemirror](https://github.com/khoben/telemirror/blob/19cf3acee1003191b7a30e337ee6cab95e59c2f9/telemirror/mirroring.py)：单账号收发、事件处理、forward 编辑限制、异常与删除路径。
2. [telemirror 存储接口与 binding_id](https://github.com/khoben/telemirror/blob/19cf3acee1003191b7a30e337ee6cab95e59c2f9/telemirror/storage.py)：映射字段、内存/PG 实现与清理行为。
3. [telemirror 配置](https://github.com/khoben/telemirror/blob/19cf3acee1003191b7a30e337ee6cab95e59c2f9/config.py)、[发送适配](https://github.com/khoben/telemirror/blob/19cf3acee1003191b7a30e337ee6cab95e59c2f9/telemirror/_patch/sending.py)、[依赖](https://github.com/khoben/telemirror/blob/19cf3acee1003191b7a30e337ee6cab95e59c2f9/requirements.txt)、[启动与健康端点](https://github.com/khoben/telemirror/blob/19cf3acee1003191b7a30e337ee6cab95e59c2f9/main.py)。
4. [telemirror GPL-3.0](https://github.com/khoben/telemirror/blob/19cf3acee1003191b7a30e337ee6cab95e59c2f9/LICENSE)、[GNU：GPL 源码提供与分发](https://www.gnu.org/licenses/gpl-faq.html#GPLRequireSourcePostedPublic)。许可结论需结合实际组合与交付方式复核。
5. [LangBot HTTP Bot 集成文档](https://github.com/langbot-app/LangBot/blob/b10139bd831cb457cf28a4a73995c6c099817864/docs/platforms/http-bot.md)、[HTTP Bot 源码](https://github.com/langbot-app/LangBot/blob/b10139bd831cb457cf28a4a73995c6c099817864/src/langbot/pkg/platform/sources/http_bot.py)：签名、202、callback、session、sequence、有限重试与内存队列。
6. [LangBot 架构](https://github.com/langbot-app/LangBot/blob/b10139bd831cb457cf28a4a73995c6c099817864/ARCHITECTURE.md)：pipeline、平台适配、模型、历史和 runtime 边界。
7. [FBA 基线](https://github.com/fastapi-practices/fastapi-best-architecture/tree/123a44aed02daf5ea60d2a7469625c933d3bb759)、[FBA UI](https://github.com/fastapi-practices/fastapi-best-architecture-ui)、[FBA 官方文档](https://docs.fba.wu-clan.cc/)。
8. [Telethon MessageDeleted](https://docs.telethon.dev/en/stable/modules/events.html#telethon.events.messagedeleted.MessageDeleted)、[Session](https://docs.telethon.dev/en/stable/concepts/sessions.html)、[RPC errors](https://docs.telethon.dev/en/stable/concepts/errors.html)；[Telethon 当前官方仓库](https://codeberg.org/Lonami/Telethon)。

实施时以固定版本的官方协议、源码和实际测试为准；本方案中的新增接口、持久化行为、可靠性增强和性能目标不能作为上游现成能力宣传。
