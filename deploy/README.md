# 部署(架构 §13 / §15)

## 拓扑

```
edge(internal):  reverse-proxy :443 → web / control-api
app(egress NAT): control-api / task-worker / scheduler / tg-runtime-worker / langbot
data(internal):  postgres / redis / minio(可选)
ops(internal):   prometheus / grafana / pg-backup
```

- 公网仅 `:443`;DB/Redis/LangBot/metrics 均无公网端口。
- `app` 网保留出站 NAT(tg-runtime-worker → Telegram,langbot → 模型端点);生产环境由宿主防火墙/egress 代理按白名单收敛。
- 所有容器 `read_only` + `no-new-privileges` + `cap_drop: ALL`,日志 json-file 轮转。
- 不把 Docker socket 挂进任何容器;Worker 扩缩容由部署侧编排(§13.1)。

## 首次启动

```bash
cd deploy
cp .env.example .env          # 全部 CHANGE_ME 改掉;SESSION_KEK=base64 32B
mkdir -p nginx/certs          # 放入 fullchain.pem / privkey.pem
docker compose up -d postgres redis
docker compose run --rm control-api fba init   # 建库/迁移/种子(见 README.backend)
docker compose up -d          # web / control-api / task-worker / scheduler / reverse-proxy
docker compose --profile ai --profile runtime --profile backup up -d   # 按需
```

## 访问

- 站点:`https://<host>/`(唯一公网入口)
- Grafana:不经公网;`ssh -L 3000:localhost:3000` 后走 ops 网查看(容器内 3000,需 `docker compose exec`/端口转发)

## 备份与恢复(§15)

| 项 | 本栈提供 | 生产需补 |
|---|---|---|
| 全量 | `pg-backup` 每 `BACKUP_INTERVAL_SECONDS`(默认 1h)`pg_dump -Fc` → `backups` 卷 + sha256 manifest | 异地/加密存储 |
| PITR | — | postgres `wal_level=replica` + `archive_command` 到 minio/对象存储 |
| 恢复 | `backup/restore.sh` 先恢复到 `*_restore_check` 临库核对,再人工切换 | 演练剧本见下 |
| 密钥 | SESSION_KEK/DB 密码/模型密钥分开保管,不与备份同地 | KMS/Vault |

### 恢复演练 checklist(每季度/上线前必做)

1. `restore.sh <最新 dump>` → 临库核对 `delivery_job`/`tg_telegram_account` 行数。
2. 起一套 `*_restore_check` 连接的 control-api,验证列表/详情可读。
3. 核对在途 job 状态:`uncertain`/`sending` 一律人工核实(数据库备份不能回滚已发出的 Telegram 副作用)。
4. 记录 RTO 实测耗时,写回演练记录。

## 已知未实现(D 期)

- `tg-runtime-worker` 的生产宿主循环(`runtime/worker/__main__.py`:租约心跳 + 平台 `/runtime` 轮询 + LiveAdapter 接线)尚未落地,该服务在 `runtime` profile 下暂缓。
- `/metrics` 已由 FBA 挂载(prometheus_client);tg 域指标见 `docs/runbook.md` §6。
- LangBot `data/config.yaml` 的 bot/model 绑定由部署方在 `langbot_data` 卷内配置;`PLUGIN__ENABLE=false` 已在 compose 层强制。
