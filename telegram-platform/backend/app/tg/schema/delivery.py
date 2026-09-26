from typing import Any

from pydantic import Field

from backend.common.schema import SchemaBase


class GetDeliveryJobDetail(SchemaBase):
    """投递任务详情"""

    id: str
    tenant_id: str
    project_id: str
    idempotency_key: str
    kind: str
    route_id: str
    rule_id: str
    rule_version: int
    account_id: str
    source_scope: str
    source_chat_id: int
    source_message_id: int
    revision: int
    target_chat_id: int
    target_topic_id: int | None
    mode: str
    payload_ref: str | None
    payload_hash: str | None
    requires_approval: bool
    status: str
    attempt_count: int
    next_attempt_at: Any | None
    flood_wait_until: Any | None
    last_error_class: str | None
    created_at: Any | None
    updated_at: Any | None
    account_label: str | None = Field(default=None, description='账号展示标签')


class GetDeliveryJobPage(SchemaBase):
    """投递任务分页"""

    total: int
    page: int
    size: int
    items: list[GetDeliveryJobDetail]


class GetDeliveryAttemptDetail(SchemaBase):
    """投递尝试详情"""

    id: str
    job_id: str
    attempt_no: int
    worker_generation: int
    started_at: Any | None
    finished_at: Any | None
    result_status: str | None
    error_class: str | None
    request_ref: str | None


class GetDeliveryJobFull(GetDeliveryJobDetail):
    """任务详情 + 尝试记录 + 消息映射"""

    attempts: list[GetDeliveryAttemptDetail] = Field(default_factory=list)
    message_maps: list[dict[str, Any]] = Field(default_factory=list)


class RetryDeliveryParam(SchemaBase):
    """重试投递(uncertain 状态拒绝走普通重试)"""

    reason: str | None = Field(None, description='重试原因')


class CancelDeliveryParam(SchemaBase):
    """取消投递"""

    reason: str | None = Field(None, description='取消原因')
