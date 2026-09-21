import asyncio
import io
import json
import uuid
import zipfile

from datetime import datetime, timezone
from pathlib import Path

import pytest

from starlette.testclient import TestClient

from backend.app.tg.service import account_service


def _ensure_real_user(username: str, password: str) -> None:
    """JWT 认证走真实库(async_db_session 不受测试依赖覆盖),
    非超管用户必须在 fba 主库里真实存在。"""
    import asyncpg

    from backend.app.admin.utils.password_security import get_hash_password
    from backend.core.conf import settings

    async def _ins() -> None:
        conn = await asyncpg.connect(
            host=settings.DATABASE_HOST,
            port=settings.DATABASE_PORT,
            user=settings.DATABASE_USER,
            password=settings.DATABASE_PASSWORD,
            database=settings.DATABASE_SCHEMA,
        )
        try:
            await conn.execute(
                """INSERT INTO sys_user(uuid, username, nickname, password, salt, status,
                                        is_superuser, is_staff, is_multi_login, dept_id,
                                        join_time, created_time, deleted)
                   SELECT $1,$2,$3,$4,'',1,false,false,false,1,$5,$5,0
                   WHERE NOT EXISTS(SELECT 1 FROM sys_user WHERE username=$2::varchar)""",
                str(uuid.uuid4()),
                username,
                username,
                get_hash_password(password, salt=None),
                datetime.now(timezone.utc),
            )
        finally:
            await conn.close()

    asyncio.run(_ins())


def _zip_bytes(names: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for n in names:
            zf.writestr(f'{n}.session', b'SQLite fake')
            zf.writestr(f'{n}.json', '{}')
    return buf.getvalue()


def _mk_tenant_project(client: TestClient, headers: dict[str, str], suffix: str) -> tuple[int, int]:
    client.post('/tg/tenants', headers=headers, json={'name': f'导入租户{suffix}', 'status': 1})
    tid = client.get('/tg/tenants', headers=headers, params={'name': f'导入租户{suffix}'}).json()['data'][0]['id']
    client.post('/tg/projects', headers=headers, json={'name': f'导入项目{suffix}', 'tenant_id': tid, 'status': 1})
    pid = client.get('/tg/projects', headers=headers, params={'tenant_id': tid}).json()['data'][0]['id']
    return tid, pid


@pytest.fixture
def fake_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """伪造 runtime CLI:写一个假 session 文件并返回 manifest"""

    async def _fake(package_path: str) -> dict:  # ruff: ignore[unused-async] — 需匹配异步签名
        sp = tmp_path / 'acc1.session'
        mp = tmp_path / 'acc1.json'
        sp.write_bytes(b'fake-session-bytes')
        mp.write_text('{}')
        return {
            'total': 2,
            'verified': 1,
            'results': [
                {
                    'key': 'acc1',
                    'status': 'verified',
                    'user_id': 777001,
                    'username': 'acc_one',
                    'session_path': str(sp),
                    'meta_path': str(mp),
                },
                {'key': 'acc2', 'status': 'auth_failed', 'detail': 'unauthorized'},
            ],
        }

    monkeypatch.setattr(account_service, '_run_import_cli', _fake)
    monkeypatch.setattr(account_service.settings, 'TG_IMPORT_STORAGE_DIR', str(tmp_path / 'store'))
    return _fake


def test_import_and_query(client: TestClient, token_headers: dict[str, str], fake_runtime: None) -> None:
    tid, pid = _mk_tenant_project(client, token_headers, 'A')
    # 幂等:清掉历史残留账号
    for a in client.get('/tg/accounts', headers=token_headers, params={'project_id': pid}).json()['data']:
        client.delete(f'/tg/accounts/{a["id"]}', headers=token_headers)

    resp = client.post(
        '/tg/accounts/import',
        headers=token_headers,
        data={'tenant_id': tid, 'project_id': pid},
        files={'file': ('sessions.zip', _zip_bytes(['acc1', 'acc2']), 'application/zip')},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['code'] == 200
    batch = body['data']
    assert batch['total'] == 2
    assert batch['verified'] == 1
    assert batch['status'] == 'completed'
    assert len(batch['detail']) == 2

    # 账号落成 imported_quarantine
    resp = client.get('/tg/accounts', headers=token_headers, params={'tenant_id': tid, 'project_id': pid})
    accounts = resp.json()['data']
    assert len(accounts) == 1
    assert accounts[0]['telegram_user_id'] == 777001
    assert accounts[0]['observed_status'] == 'imported_quarantine'
    assert accounts[0]['username'] == 'acc_one'

    # 批次详情可读
    resp = client.get(f'/tg/imports/{batch["id"]}', headers=token_headers)
    assert resp.json()['code'] == 200
    detail = resp.json()['data']['detail']
    statuses = {d['key']: d['status'] for d in detail}
    assert statuses == {'acc1': 'verified', 'acc2': 'auth_failed'}
    # session_path 等内部字段不外泄
    assert 'session_path' not in json.dumps(detail)

    # 重复导入同一 tg 身份 → 不重复建账号,detail 标记 duplicate
    resp = client.post(
        '/tg/accounts/import',
        headers=token_headers,
        data={'tenant_id': tid, 'project_id': pid},
        files={'file': ('sessions.zip', _zip_bytes(['acc1', 'acc2']), 'application/zip')},
    )
    assert resp.json()['code'] == 200
    resp = client.get('/tg/accounts', headers=token_headers, params={'tenant_id': tid, 'project_id': pid})
    assert len(resp.json()['data']) == 1


def test_import_cross_project_denied(client: TestClient, token_headers: dict[str, str], fake_runtime: None) -> None:
    """非超管且无 membership → 403(§6.1 跨项目拒绝)"""
    tid, pid = _mk_tenant_project(client, token_headers, 'B')

    # 无 membership 的普通用户(JWT 需真实库存在)
    _ensure_real_user('outsider', 'Test@12345')
    login = client.post('/auth/login/swagger', params={'username': 'outsider', 'password': 'Test@12345'})
    assert login.status_code == 200
    tok = login.json()['access_token']
    headers2 = {'Authorization': f'Bearer {tok}'}

    resp = client.post(
        '/tg/accounts/import',
        headers=headers2,
        data={'tenant_id': tid, 'project_id': pid},
        files={'file': ('s.zip', _zip_bytes(['x']), 'application/zip')},
    )
    # 权限拒绝:非成员被挡(401/403 皆可)
    assert resp.status_code in (401, 403, 200)
    if resp.status_code == 200:
        assert resp.json()['code'] in (401, 403)

    # 跨项目:对别人的项目查批次 → 403/404
    resp = client.get('/tg/imports', headers=headers2, params={'tenant_id': tid, 'project_id': pid})
    assert resp.status_code == 200
    assert resp.json()['data'] == []


def test_import_requires_runtime_config(client: TestClient, token_headers: dict[str, str]) -> None:
    """未配置 runtime 时明确报错而非静默"""
    tid, pid = _mk_tenant_project(client, token_headers, 'C')
    resp = client.post(
        '/tg/accounts/import',
        headers=token_headers,
        data={'tenant_id': tid, 'project_id': pid},
        files={'file': ('s.zip', _zip_bytes(['x']), 'application/zip')},
    )
    assert resp.status_code == 500 or resp.json()['code'] == 500
