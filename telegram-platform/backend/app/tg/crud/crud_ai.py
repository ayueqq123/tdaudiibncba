from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.tg.model.ai import TgAiBinding, TgAiCallback, TgAiConversation, TgAiRun
from backend.app.tg.schema.ai import (
    CreateAiBindingParam,
    CreateAiCallbackParam,
    CreateAiConversationParam,
    CreateAiRunParam,
)


class CRUDAiBinding(CRUDPlus[TgAiBinding]):
    """LangBot 绑定表操作"""

    async def get(self, db: AsyncSession, pk: int) -> TgAiBinding | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_by_uuid(self, db: AsyncSession, uuid: str) -> TgAiBinding | None:
        return await self.select_model_by_column(db, uuid=uuid, deleted=0)

    async def get_all(
        self, db: AsyncSession, tenant_id: int | None = None, project_id: int | None = None
    ) -> Sequence[TgAiBinding]:
        filters = {k: v for k, v in {'tenant_id': tenant_id, 'project_id': project_id}.items() if v is not None}
        return await self.select_models(db, deleted=0, **filters)

    async def create(self, db: AsyncSession, obj: CreateAiBindingParam) -> TgAiBinding:
        return await self.create_model(db, obj)

    async def update_status(self, db: AsyncSession, pk: int, status: str) -> int:
        return await self.update_model(db, pk, {'status': status})


class CRUDAiConversation(CRUDPlus[TgAiConversation]):
    """AI 会话表操作"""

    async def get(self, db: AsyncSession, pk: int) -> TgAiConversation | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_by_session(self, db: AsyncSession, session_id: str) -> TgAiConversation | None:
        return await self.select_model_by_column(db, session_id=session_id, deleted=0)

    async def get_by_scope(
        self,
        db: AsyncSession,
        tenant_id: int,
        project_id: int,
        chat_id: int,
        topic_id: int | None,
        agent_key: str | None,
        context_epoch: int,
    ) -> TgAiConversation | None:
        return await self.select_model_by_column(
            db,
            tenant_id=tenant_id,
            project_id=project_id,
            chat_id=chat_id,
            topic_id=topic_id,
            agent_key=agent_key,
            context_epoch=context_epoch,
            deleted=0,
        )

    async def get_all(
        self, db: AsyncSession, tenant_id: int | None = None, project_id: int | None = None
    ) -> Sequence[TgAiConversation]:
        filters = {k: v for k, v in {'tenant_id': tenant_id, 'project_id': project_id}.items() if v is not None}
        return await self.select_models(db, deleted=0, **filters)

    async def create(self, db: AsyncSession, obj: CreateAiConversationParam) -> TgAiConversation:
        return await self.create_model(db, obj)

    async def update_fields(self, db: AsyncSession, pk: int, fields: dict) -> int:
        return await self.update_model(db, pk, fields)


class CRUDAiRun(CRUDPlus[TgAiRun]):
    """AI 运行表操作"""

    async def get(self, db: AsyncSession, pk: int) -> TgAiRun | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_by_uuid(self, db: AsyncSession, uuid: str) -> TgAiRun | None:
        return await self.select_model_by_column(db, uuid=uuid, deleted=0)

    async def get_active_by_session(self, db: AsyncSession, session_id: str) -> TgAiRun | None:
        for status in ('pending', 'dispatched', 'running'):
            run = await self.select_model_by_column(db, session_id=session_id, status=status, deleted=0)
            if run is not None:
                return run
        return None

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: int | None = None,
        project_id: int | None = None,
        status: str | None = None,
    ) -> Sequence[TgAiRun]:
        filters = {
            k: v
            for k, v in {'tenant_id': tenant_id, 'project_id': project_id, 'status': status}.items()
            if v is not None
        }
        return await self.select_models(db, deleted=0, **filters)

    async def create(self, db: AsyncSession, obj: CreateAiRunParam) -> TgAiRun:
        return await self.create_model(db, obj)

    async def update_fields(self, db: AsyncSession, pk: int, fields: dict) -> int:
        return await self.update_model(db, pk, fields)


class CRUDAiCallback(CRUDPlus[TgAiCallback]):
    """AI 回调表操作(只写不改,唯一键防重放)"""

    async def get_all_for_run(self, db: AsyncSession, ai_run_id: int) -> Sequence[TgAiCallback]:
        return await self.select_models(db, ai_run_id=ai_run_id, deleted=0)

    async def create(self, db: AsyncSession, obj: CreateAiCallbackParam) -> TgAiCallback:
        return await self.create_model(db, obj)

    async def update_link(self, db: AsyncSession, pk: int, ai_run_id: int, link_status: str) -> int:
        return await self.update_model(db, pk, {'ai_run_id': ai_run_id, 'link_status': link_status})


ai_binding_dao: CRUDAiBinding = CRUDAiBinding(TgAiBinding)
ai_conversation_dao: CRUDAiConversation = CRUDAiConversation(TgAiConversation)
ai_run_dao: CRUDAiRun = CRUDAiRun(TgAiRun)
ai_callback_dao: CRUDAiCallback = CRUDAiCallback(TgAiCallback)
