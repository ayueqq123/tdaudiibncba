import asyncio
import hashlib
import json
import os
import shutil
import uuid

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
    # 追加而非覆盖:容器里 telethon 等依赖已在 PYTHONPATH(如 /app/dependencies)
    existing = env.get('PYTHONPATH')
    env['PYTHONPATH'] = (
        f'{settings.TG_RUNTIME_DIR}{os.pathsep}{existing}' if existing else settings.TG_RUNTIME_DIR
    )
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


_LOGIN_PENDING: dict[str, dict[str, Any]] = {}
_LOGIN_TTL_S = 600


def _purge_pending() -> None:
    now = timezone.now().timestamp()
    for lid, st in list(_LOGIN_PENDING.items()):
        if st['expires'] < now:
            Path(st['session_path']).unlink(missing_ok=True)
            _LOGIN_PENDING.pop(lid, None)


async def _run_login_cli(mode: str, args: list[str], stdin_payload: dict | None = None) -> dict[str, Any]:
    """spawn runtime code_login CLI(GPL 边界:不 import)。返回 stdout JSON。"""
    if not settings.TG_RUNTIME_DIR or not settings.TG_RUNTIME_PYTHON:
        raise errors.ServerError(msg='未配置 TG_RUNTIME_DIR/TG_RUNTIME_PYTHON')
    env = dict(os.environ)
    existing = env.get('PYTHONPATH')
    env['PYTHONPATH'] = (
        f'{settings.TG_RUNTIME_DIR}{os.pathsep}{existing}' if existing else settings.TG_RUNTIME_DIR
    )
    proc = await asyncio.create_subprocess_exec(
        settings.TG_RUNTIME_PYTHON,
        '-m',
        'runtime.account.code_login',
        mode,
        *args,
        cwd=settings.TG_RUNTIME_DIR,
        env=env,
        stdin=asyncio.subprocess.PIPE if stdin_payload is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdin_data = json.dumps(stdin_payload).encode() if stdin_payload is not None else None
    stdout, stderr = await proc.communicate(input=stdin_data)
    line = stdout.decode().strip().splitlines()
    if not line:
        raise errors.ServerError(msg=f'登录子进程无输出 rc={proc.returncode}: {stderr.decode()[:300]}')
    return json.loads(line[-1])


_LOGIN_ERR = {
    'code_invalid': '验证码错误',
    'code_expired': '验证码已过期,请重新发起登录',
    'phone_invalid': '手机号格式错误',
    'phone_banned': '该号码已被 Telegram 封禁',
    'phone_unoccupied': '该号码未注册 Telegram',
}


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
    async def login_start(*, db: AsyncSession, request: Request, obj) -> dict[str, Any]:
        """验证码登录第一步:发送验证码。pending 会话存内存(TTL 10min)。"""
        await AccountService._check_scope(db, request, obj.tenant_id, obj.project_id)
        _purge_pending()
        login_id = uuid.uuid4().hex
        pending_dir = Path(settings.TG_IMPORT_STORAGE_DIR) / '.pending'
        pending_dir.mkdir(parents=True, exist_ok=True)
        session_path = str(pending_dir / f'{login_id}.session')
        args = [
            '--session', session_path,
            '--api-id', str(obj.api_id),
            '--api-hash', obj.api_hash,
            '--phone', obj.phone,
        ]
        if obj.device:
            args += ['--device', obj.device]
        if obj.app_version:
            args += ['--app-version', obj.app_version]
        result = await _run_login_cli('send', args)
        if not result.get('ok'):
            Path(session_path).unlink(missing_ok=True)
            err = result.get('error') or {}
            status = err.get('status')
            if status == 'flood_wait':
                raise errors.RequestError(msg=f"操作频繁,请 {err.get('seconds', 60)} 秒后重试")
            raise errors.RequestError(msg=_LOGIN_ERR.get(status, err.get('detail', '发送验证码失败')))
        _LOGIN_PENDING[login_id] = {
            'session_path': session_path,
            'tenant_id': obj.tenant_id,
            'project_id': obj.project_id,
            'user_id': request.user.id,
            'phone': obj.phone,
            'api_id': obj.api_id,
            'api_hash': obj.api_hash,
            'device': obj.device,
            'app_version': obj.app_version,
            'phone_code_hash': result['phone_code_hash'],
            'expires': timezone.now().timestamp() + _LOGIN_TTL_S,
        }
        return {'login_id': login_id, 'ttl': _LOGIN_TTL_S}

    @staticmethod
    async def login_complete(*, db: AsyncSession, request: Request, obj) -> dict[str, Any]:
        """验证码登录第二步:提交验证码 → 落 session+meta → 建账号。"""
        _purge_pending()
        st = _LOGIN_PENDING.get(obj.login_id)
        if st is None:
            raise errors.RequestError(msg='登录会话已过期,请重新发起')
        if st['user_id'] != request.user.id and not request.user.is_superuser:
            raise errors.ForbiddenError(msg='无权完成该登录')
        await AccountService._check_scope(db, request, st['tenant_id'], st['project_id'])
        args = [
            '--session', st['session_path'],
            '--api-id', str(st['api_id']),
            '--api-hash', st['api_hash'],
            '--phone', st['phone'],
            '--code-hash', st['phone_code_hash'],
        ]
        if st['device']:
            args += ['--device', st['device']]
        if st['app_version']:
            args += ['--app-version', st['app_version']]
        result = await _run_login_cli('signin', args, {'code': obj.code, 'password': obj.password})
        if not result.get('ok'):
            if result.get('need_password'):
                return {'need_password': True}
            err = result.get('error') or {}
            status = err.get('status')
            if status == 'flood_wait':
                raise errors.RequestError(msg=f"操作频繁,请 {err.get('seconds', 60)} 秒后重试")
            raise errors.RequestError(msg=_LOGIN_ERR.get(status, err.get('detail', '登录失败')))
        # 登录成功:session 文件 + meta json 移入登录目录,结构同导入批次
        uid = result.get('user_id')
        existing = await telegram_account_dao.get_by_tg_user(db, uid) if uid else None
        if existing is not None:
            Path(st['session_path']).unlink(missing_ok=True)
            _LOGIN_PENDING.pop(obj.login_id, None)
            raise errors.RequestError(msg=f'该 Telegram 身份已存在账号 id={existing.id}')
        login_dir = Path(settings.TG_IMPORT_STORAGE_DIR) / f'login-{uuid.uuid4().hex}'
        login_dir.mkdir(parents=True, exist_ok=True)
        key = (result.get('phone') or st['phone']).lstrip('+') or uuid.uuid4().hex
        session_dst = login_dir / f'{key}.session'
        shutil.move(st['session_path'], session_dst)
        (login_dir / f'{key}.json').write_text(
            json.dumps(
                {
                    'app_id': st['api_id'],
                    'app_hash': st['api_hash'],
                    'device': st['device'],
                    'app_version': st['app_version'],
                }
            ),
            encoding='utf-8',
        )
        account = await telegram_account_dao.create(
            db,
            CreateTgAccountParam(
                tenant_id=st['tenant_id'],
                project_id=st['project_id'],
                phone=result.get('phone') or st['phone'],
                telegram_user_id=uid,
                username=result.get('username'),
                secret_ref=str(session_dst.relative_to(settings.TG_IMPORT_STORAGE_DIR)),
                observed_status='imported_quarantine',
            ),
        )
        _LOGIN_PENDING.pop(obj.login_id, None)
        return {'account_id': account.id, 'username': result.get('username'), 'telegram_user_id': uid}

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
