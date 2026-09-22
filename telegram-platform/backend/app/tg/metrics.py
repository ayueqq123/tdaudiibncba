from prometheus_client import Counter, Gauge

# §18.1:metrics 标签限基数——只用低基数枚举值,不带 message_id/手机号/文本

tg_ai_callback_total = Counter(
    'tg_ai_callback_total',
    'LangBot 回调处理计数',
    ['result'],  # linked | pending_link | dedup | rejected
)

tg_ai_run_total = Counter(
    'tg_ai_run_total',
    'AI run 终态计数',
    ['status'],  # completed | incomplete | failed | cancelled
)

tg_delivery_job_created_total = Counter(
    'tg_delivery_job_created_total',
    '平台创建的投递任务计数',
    ['kind'],  # send_message | ...
)

tg_ai_run_active = Gauge(
    'tg_ai_run_active',
    '当前生成中的 AI run 数',
)
