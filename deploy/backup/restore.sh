#!/bin/sh
# 恢复(人工执行;默认恢复到 *临库* 核对,确认后再切换):
#   ./restore.sh /backups/tg-platform-20260101T000000Z.dump
set -eu

DUMP="${1:?usage: restore.sh <dump-file>}"
DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DATABASE_USER:-tg_platform}"
DB_NAME="${DATABASE_SCHEMA:-fba}"
RESTORE_DB="${RESTORE_DB:-${DB_NAME}_restore_check}"

echo "[restore] 1/4 校验 manifest"
manifest="${DUMP%.dump}.manifest"
if [ -f "$manifest" ]; then
    expected="$(grep '^sha256=' "$manifest" | cut -d= -f2)"
    actual="$(sha256sum "$DUMP" | cut -d' ' -f1)"
    [ "$expected" = "$actual" ] || { echo "manifest sha256 不匹配"; exit 1; }
    echo "[restore] sha256 OK"
else
    echo "[restore] 警告:无 manifest,跳过校验" >&2
fi

echo "[restore] 2/4 恢复到临库 $RESTORE_DB(生产数据不动)"
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS $RESTORE_DB" \
    -c "CREATE DATABASE $RESTORE_DB"
pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$RESTORE_DB" \
    --no-owner --no-acl "$DUMP"

echo "[restore] 3/4 一致性抽查"
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$RESTORE_DB" -c "
    SELECT count(*) AS delivery_jobs FROM delivery_job;
    SELECT count(*) AS accounts FROM tg_telegram_account;
"

cat <<EOF
[restore] 4/4 核对无误后切换:
  1. 停 app:docker compose stop control-api task-worker scheduler tg-runtime-worker
  2. 备份当前库并重命名/切连接(ALTER DATABASE ... RENAME 或改 DATABASE_SCHEMA)
  3. 起 app 后人工核查 uncertain/在途投递——恢复对已发出的 Telegram 副作用不生效(§15)
EOF
