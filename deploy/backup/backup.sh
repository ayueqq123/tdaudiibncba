#!/bin/sh
# TG 平台逻辑备份(pg_dump 全量 + 清单)。
# 生产 RPO≤15min 依赖 WAL 归档——本脚本是保底全量,README §15 另有 PITR 配置说明。
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DATABASE_USER:-tg_platform}"
DB_NAME="${DATABASE_SCHEMA:-fba}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-3600}"

mkdir -p "$BACKUP_DIR"

while :; do
    ts="$(date -u +%Y%m%dT%H%M%SZ)"
    out="$BACKUP_DIR/tg-platform-$ts.dump"
    manifest="$BACKUP_DIR/tg-platform-$ts.manifest"

    echo "[backup] pg_dump $DB_NAME -> $out"
    if pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        -Fc --no-owner --no-acl -f "$out.tmp"; then
        mv "$out.tmp" "$out"
        {
            echo "timestamp=$ts"
            echo "database=$DB_NAME"
            echo "dump=$out"
            echo "sha256=$(sha256sum "$out" | cut -d' ' -f1)"
            echo "pg_version=$(pg_dump --version | awk '{print $3}')"
        } > "$manifest"
        echo "[backup] done $(du -h "$out" | cut -f1)"
    else
        rm -f "$out.tmp"
        echo "[backup] FAILED at $ts" >&2
    fi

    # 过期清理(按修改时间,保护最近 RETENTION_DAYS 天)
    find "$BACKUP_DIR" -name 'tg-platform-*.dump' -mtime "+$RETENTION_DAYS" -delete
    find "$BACKUP_DIR" -name 'tg-platform-*.manifest' -mtime "+$RETENTION_DAYS" -delete

    sleep "$INTERVAL"
done
