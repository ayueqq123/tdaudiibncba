from datetime import datetime

from pydantic import Field

from backend.common.schema import SchemaBase


class CreateReplyCandidateParam(SchemaBase):
    """创建回复候选(内部/AI 适配器使用)"""

    tenant_id: int
    project_id: int
    account_id: int
    target_chat_id: int
    content: str
    content_hash: str = Field(description='规范化内容 hash')
    expires_at: datetime = Field(description='候选过期时间')
    agent_run_id: str | None = None
    rule_id: int | None = None
    target_topic_id: int | None = None
    reply_to_source_id: int | None = None
    attachments: dict | None = None


class CreateApprovalParam(SchemaBase):
    """创建审批单参数(service 内部)"""

    tenant_id: int
    project_id: int
    candidate_id: int
    candidate_version: int
    content_hash: str
    expires_at: datetime
    status: str = 'pending'


class ApproveCandidateParam(SchemaBase):
    """审批通过(绑定候选版本 + 内容 hash,§10.1)"""

    candidate_version: int = Field(description='期望候选版本,不符则拒绝')
    content_hash: str = Field(description='审核时看到的内容 hash')
    reason: str | None = None


class RejectCandidateParam(SchemaBase):
    """审批拒绝"""

    candidate_version: int = Field(description='期望候选版本')
    content_hash: str = Field(description='审核时看到的内容 hash')
    reason: str | None = None


class GetReplyCandidateDetail(SchemaBase):
    """候选详情"""

    id: int
    uuid: str
    tenant_id: int
    project_id: int
    account_id: int
    agent_run_id: str | None
    rule_id: int | None
    target_chat_id: int
    target_topic_id: int | None
    reply_to_source_id: int | None
    content: str
    attachments: dict | None
    content_hash: str
    version: int
    expires_at: datetime
    status: str


class GetApprovalDetail(SchemaBase):
    """审批详情"""

    id: int
    uuid: str
    tenant_id: int
    project_id: int
    candidate_id: int
    candidate_version: int
    content_hash: str
    expires_at: datetime
    status: str
    reviewer_id: int | None
    decided_at: datetime | None
    reason: str | None
