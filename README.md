# tdaudiibncba — Telegram 自动化平台

Userbot 多账号 + 消息 Clone + AI 群聊 + 客户管理后台的私有化交付项目。

设计文档见 `docs/`:

- `docs/telegram-platform-architecture.md` — 目标架构 v1.0(开发拆解与生产验收基线)
- `docs/telegram-open-source-plan.html` — 开源选型调研与开发路线

## 仓库布局

```text
telegram-platform/    平台主体(FBA 派生)
  backend/            FBA 后端:账号、规则、审批、投递、审计等业务模块
  web/                FBA 配套 Vue 管理前端
  contracts/          HTTP OpenAPI、事件 JSON Schema
  deploy/             镜像编排、监控、备份部署说明
  tests/              API、跨租户、集成、故障注入测试

telegram-runtime/     telemirror GPL 派生运行时
  telemirror/         上游核心(基线见 UPSTREAM.md)+ 平台补丁
  runtime/            新增:account / ingest / planner / delivery / storage / control
  UPSTREAM.md         上游基线 SHA、补丁清单、升级记录

docs/                 设计与调研文档
```

## 许可证边界

- `telegram-runtime/` 是 [telemirror](https://github.com/khoben/telemirror)(GPL-3.0)的派生作品,
  该子树整体按 GPL-3.0 授权,向客户交付时须附对应源码。详见 `telegram-runtime/LICENSE` 与 `UPSTREAM.md`。
- `telegram-platform/` 及仓库其余部分的许可证待客户交付模式确认;在确认前视为专有代码。
- **不要把 `telegram-runtime/` 下的代码复制到 `telegram-platform/`**;两边通过受控的
  HTTP/JSON 契约与共享数据库 schema 交互。

## 基线版本

| 组件 | 基线 |
| --- | --- |
| telemirror | `19cf3acee1003191b7a30e337ee6cab95e59c2f9` |
| fastapi-best-architecture | `123a44aed02daf5ea60d2a7469625c933d3bb759` |
| fastapi-best-architecture-ui | `9f4040ce6b86ef414d9b47a243661049f0dd945f` |
| Telethon | `1.44.0`(随 telemirror requirements 钉死) |
| LangBot | 外部部署,经 HTTP Bot 集成,不经 vendor |
