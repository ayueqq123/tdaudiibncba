"""TG 域周期任务:ai_run 截止清扫(§9.5 回调缺失->incomplete 可见)"""

from celery import shared_task

from backend.app.tg.service.ai_service import AiService
from backend.database.db import async_db_session


@shared_task
async def tg_ai_sweep_deadlines() -> str:
    """超时 AI 运行 → incomplete,会话锁释放。"""
    async with async_db_session.begin() as db:
        n = await AiService.sweep_deadlines(db=db)
        return f'swept={n}'
