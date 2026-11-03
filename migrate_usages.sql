-- 1. 加列
ALTER TABLE tg_telegram_account ADD COLUMN IF NOT EXISTS usages json;

-- 2. 现有 usage 单值 → usages 数组
UPDATE tg_telegram_account SET usages = json_build_array(usage)
WHERE usage IS NOT NULL AND usages IS NULL;

-- 3. 按在用情况自动归组(clone 规则监听号+号池→clone;ai 绑定/私信回复→ai),与已有标记合并
WITH clone_ids AS (
  SELECT account_id AS id FROM tg_clone_rule WHERE deleted = 0
  UNION
  SELECT e.value::bigint FROM tg_clone_rule r, json_array_elements_text(r.sender_account_ids) e WHERE r.deleted = 0
), ai_ids AS (
  SELECT account_id AS id FROM tg_ai_binding WHERE deleted = 0
  UNION SELECT account_id FROM tg_ai_private_reply WHERE deleted = 0
), wanted AS (
  SELECT id, 'clone'::text AS g FROM clone_ids
  UNION SELECT id, 'ai'::text FROM ai_ids
  UNION SELECT id AS id, usage AS g FROM tg_telegram_account WHERE usage IS NOT NULL
), grouped AS (
  SELECT id, json_agg(DISTINCT g ORDER BY g) AS groups FROM wanted WHERE g IS NOT NULL GROUP BY id
)
UPDATE tg_telegram_account a SET usages = grouped.groups
FROM grouped WHERE a.id = grouped.id;

-- 4. 结果
SELECT usages, count(*) FROM tg_telegram_account WHERE deleted = 0 GROUP BY usages ORDER BY 1;
