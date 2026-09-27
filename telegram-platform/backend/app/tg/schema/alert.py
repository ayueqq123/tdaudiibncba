from pydantic import Field

from backend.common.schema import SchemaBase


class AckAlertParam(SchemaBase):
    """标记告警已处理"""

    keys: list[str] = Field(..., min_length=1, max_length=500, description='告警 key 列表')
