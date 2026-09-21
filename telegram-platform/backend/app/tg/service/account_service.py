import asyncio
import hashlib
import json
import os
import shutil

from pathlib import Path
from typing import Any

from fastapi import Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tg.crud.crud_import_batch import import_batch_dao
from backend.app.tg.crud.crud_membership import membership_dao
from backend.app.tg.crud.crud_project import project_dao
from backend.app.tg.crud.crud_telegram_account import telegram_account_dao
from backend.app.tg.model import TgImportBatch, TgTelegramAccount
from backend.app.tg.schema.import_batch import CreateImportBatchParam
from backend.app.tg.schema.telegram_account import CreateTgAccountParam, UpdateTgAccountParam
from backend.common.exception import errors
from backend.core.conf import settings
from backend.utils.timezone import timezone

# 验证通过但尚未人工启用的账号默认进入隔离态(§5.1.1)
STATUS_BY_IMPORT_RESULT = {
    'verified': 'imported_quarantine',
    'auth_failed': 'reauth_required',
    '2fa_locked': 'imported_quarantine',
    'spamblocked': 'imported_quarantine',
    'deactivated': 'disabled',
    'invalid_format': None,  # 不建账号
    'error': None,
}


async def _run_import_cli(package_path: str) -> dict[str, Any]:
    """跨进程调用 telegram-runtime 的 session_import(GPL 边界:不 import,只 spawn)。

    返回 --json manifest: {total, verified, results:[{key,status,user_id,...,session_path}]}
    """
    if not settings.TG_RUNTIME_DIR or not settings.TG_RUNTIME_PYTHON:
        raise errors.ServerError(msg='未配置 TG_RUNTIME_DIR/TG_RUNTIME_PYTHON,无法执行导入验证')
    env = dict(os.environ)
    env['PYTHONPATH'] = settings.TG_RUNTIME_DIR
    proc = await asyncio.create_subprocess_exec(
        settings.TG_RUNTIME_PYTHON,
        '-m',
        'runtime.account.session_import',
        package_path,
        '--json',
        '--timeout',
        str(settings.TG_IMPORT_ITEM_TIMEOUT),
        cwd=settings.TG_RUNTIME_DIR,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    # 退出码 0/1 都表示验证跑完(1=存在失败项);其他为基础设施错误
    if proc.returncode not in (0, 1, 2) or not stdout.strip():
        raise errors.ServerError(msg=f'导入验证子进程失败 rc={proc.returncode}: {stderr.decode()[:500]}')
    return json.loads(stdout.decode())


class AccountService:
    """Telegram 账号服务类"""

    @staticmethod
    async def _check_scope(db: AsyncSession, request: Request, tenant_id: int, project_id: int) -> None:
        """跨项目拒绝:操作者必须是该 (tenant, project) 的成员,或是超管(§6.1)"""
        if request.user.is_superuser:
            return
        member = await membership_dao.get_by_scope(db, tenant_id, project_id, request.user.id)
        if not member:
            raise errors.ForbiddenError(msg='无该项目权限')

    @staticmethod
    async def get(*, db: AsyncSession, request: Request, pk: int) -> TgTelegramAccount:
        account = await telegram_account_dao.get(db, pk)
        if not account:
            raise errors.NotFoundError(msg='账号不存在')
        await AccountService._check_scope(db, request, account.tenant_id, account.project_id)
        return account

    @staticmethod
    async def get_all(
        *,
        db: AsyncSession,
        request: Request,
        tenant_id: int | None = None,
        project_id: int | None = None,
        status: str | None = None,
    ) -> list[TgTelegramAccount]:
        accounts = list(await telegram_account_dao.get_all(db, tenant_id, project_id, status))
        if request.user.is_superuser:
            return accounts
        memberships = await membership_dao.get_all(db, user_id=request.user.id)
        scopes = {(m.tenant_id, m.project_id) for m in memberships}
        return [a for a in accounts if (a.tenant_id, a.project_id) in scopes]

    @staticmethod
    async def update(*, db: AsyncSession, request: Request, pk: int, obj: UpdateTgAccountParam) -> int:
        account = await telegram_account_dao.get(db, pk)
        if not account:
            raise errors.NotFoundError(msg='账号不存在')
        await AccountService._check_scope(db, request, account.tenant_id, account.project_id)
        return await telegram_account_dao.update(db, pk, obj)

    @staticmethod
    async def delete(*, db: AsyncSession, request: Request, pk: int) -> int:
        account = await telegram_account_dao.get(db, pk)
        if not account:
            raise errors.NotFoundError(msg='账号不存在')
        await AccountService._check_scope(db, request, account.tenant_id, account.project_id)
        return await telegram_account_dao.delete(db, pk)

    @staticmethod
    async def import_zip(
        *, db: AsyncSession, request: Request, tenant_id: int, project_id: int, file: UploadFile
    ) -> TgImportBatch:
        """上传 zip → 存盘 → runtime CLI 验证 → 落库(账号 + 批次审计)。

        §5.1.1:验证只做 connect+getMe;失败项不落账号;验证过的 session 文件
        移入批次目录,secret_ref 记录相对路径(后续由 KMS/envelope 接管)。
        """
        await AccountService._check_scope(db, request, tenant_id, project_id)
        if not await project_dao.get(db, project_id):
            raise errors.NotFoundError(msg='项目不存在')
        project = await project_dao.get(db, project_id)
        if project.tenant_id != tenant_id:
            raise errors.ForbiddenError(msg='项目不属于该租户')

        content = await file.read()
        if len(content) > settings.TG_IMPORT_MAX_SIZE_MB * 1024 * 1024:
            raise errors.RequestError(msg='文件超过大小上限')
        sha = hashlib.sha256(content).hexdigest()

        batch = await import_batch_dao.create(
            db,
            CreateImportBatchParam(
                tenant_id=tenant_id,
                project_id=project_id,
                operator_id=request.user.id,
                filename=file.filename or 'upload.zip',
                file_sha256=sha,
            ),
        )
        await db.flush()

        batch_dir = Path(settings.TG_IMPORT_STORAGE_DIR) / batch.uuid
        batch_dir.mkdir(parents=True, exist_ok=True)
        pkg_path = batch_dir / 'package.zip'
        pkg_path.write_bytes(content)

        try:
            manifest = await _run_import_cli(str(pkg_path))
        except Exception:
            await import_batch_dao.update(
                db,
                batch.id,
                {
                    'status': 'failed',
                    'finished_at': timezone.now(),
                    'detail': [{'key': '*', 'status': 'error', 'detail': 'import subprocess failed'}],
                },
            )
            raise

        detail: list[dict[str, Any]] = []
        created = 0
        for r in manifest.get('results', []):
            item_status = STATUS_BY_IMPORT_RESULT.get(r.get('status'))
            entry = {k: v for k, v in r.items() if k not in ('session_path', 'meta_path')}
            if item_status is not None and r.get('session_path'):
                # 幂等:同一 Telegram 身份已存在则不重复建账号(§6.2)
                existing = None
                if r.get('user_id'):
                    existing = await telegram_account_dao.get_by_tg_user(db, r['user_id'])
                if existing is not None:
                    entry['status'] = 'duplicate'
                    entry['detail'] = f'已存在账号 id={existing.id}'
                else:
                    session_dst = batch_dir / f'{r["key"]}.session'
                    shutil.copy2(r['session_path'], session_dst)
                    if r.get('meta_path'):
                        shutil.copy2(r['meta_path'], batch_dir / f'{r["key"]}.json')
                    await telegram_account_dao.create(
                        db,
                        CreateTgAccountParam(
                            tenant_id=tenant_id,
                            project_id=project_id,
                            import_batch_id=batch.id,
                            telegram_user_id=r.get('user_id'),
                            username=r.get('username'),
                            secret_ref=str(session_dst.relative_to(settings.TG_IMPORT_STORAGE_DIR)),
                            observed_status=item_status,
                            last_error=r.get('detail'),
                        ),
                    )
                    created += 1
            detail.append(entry)

        total = manifest.get('total', len(detail))
        await import_batch_dao.update(
            db,
            batch.id,
            {
                'total': total,
                'verified': manifest.get('verified', created),
                'failed': total - manifest.get('verified', created),
                'status': 'completed',
                'detail': detail,
                'finished_at': timezone.now(),
            },
        )
        return await import_batch_dao.get(db, batch.id)

    @staticmethod
    async def get_import(*, db: AsyncSession, request: Request, batch_id: int) -> TgImportBatch:
        batch = await import_batch_dao.get(db, batch_id)
        if not batch:
            raise errors.NotFoundError(msg='导入批次不存在')
        await AccountService._check_scope(db, request, batch.tenant_id, batch.project_id)
        return batch

    @staticmethod
    async def get_imports(
        *, db: AsyncSession, request: Request, tenant_id: int | None = None, project_id: int | None = None
    ) -> list[TgImportBatch]:
        batches = list(await import_batch_dao.get_all(db, tenant_id, project_id))
        if request.user.is_superuser:
            return batches
        memberships = await membership_dao.get_all(db, user_id=request.user.id)
        scopes = {(m.tenant_id, m.project_id) for m in memberships}
        return [b for b in batches if (b.tenant_id, b.project_id) in scopes]


account_service: AccountService = AccountService()
