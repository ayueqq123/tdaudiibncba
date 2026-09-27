"""TG 域周期任务:ai_run 截止清扫(§9.5 回调缺失->incomplete 可见)"""

import asyncio

from celery import shared_task

from backend.app.tg.service.ai_service import AiService
from backend.database.db import async_db_session


@shared_task
async def tg_ai_sweep_deadlines() -> str:
    """超时 AI 运行 → incomplete,会话锁释放。"""
    async with async_db_session.begin() as db:
        n = await AiService.sweep_deadlines(db=db)
        return f'swept={n}'


@shared_task
async def tg_ai_openai_generate(run_id: int) -> str:
    """炒群延迟生成:到点后调模型 → 候选 → 审批/自动发送。run 未提交可见时短暂重试。"""
    for _ in range(3):
        async with async_db_session.begin() as db:
            result = await AiService.run_deferred_openai(db=db, run_id=run_id)
        if result != 'missing':
            return result
        await asyncio.sleep(2)
    return 'missing'
