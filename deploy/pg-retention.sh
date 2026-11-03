#!/bin/bash
# 每日清理:已处理 inbox/投递记录保留 7 天,操作日志留 30 天
set -u
del_batch() {
  local label="$1" table="$2" where="$3"
  while :; do
    out=$(docker exec tg-platform-postgres-1 psql -U tg_platform -d fba -Atc \
      "DELETE FROM $table WHERE ctid IN (SELECT ctid FROM $table WHERE $where LIMIT 50000)" 2>&1 | tail -1)
    n="${out#DELETE }"
    echo "$(date '+%F %T') $label: $out"
    if ! [[ "$n" =~ ^[0-9]+$ ]]; then echo "$label: non-delete output, aborting batch"; break; fi
    [ "$n" -lt 50000 ] && break
    sleep 0.5
  done
}
del_batch event_inbox      event_inbox      "processed AND created_at < now() - interval '7 days'"
del_batch delivery_attempt delivery_attempt "started_at < now() - interval '7 days'"
del_batch delivery_job     delivery_job     "status IN ('succeeded','failed_permanent','cancelled','dead_letter') AND updated_at < now() - interval '7 days' AND NOT EXISTS (SELECT 1 FROM delivery_attempt a WHERE a.job_id = delivery_job.id)"
del_batch sys_opera_log    sys_opera_log    "opera_time < now() - interval '7 days'"
