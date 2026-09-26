import asyncio
import uuid

from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from starlette.testclient import TestClient


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


async def _conn() -> asyncpg.Connection:
    from backend.core.conf import settings

    return await asyncpg.connect(
        host=settings.DATABASE_HOST,
        port=settings.DATABASE_PORT,
        user=settings.DATABASE_USER,
        password=settings.DATABASE_PASSWORD,
        database=f'{settings.DATABASE_SCHEMA}_test',
    )


async def _fetch_uuid(table: str, pk: int) -> str:
    conn = await _conn()
    try:
        return await conn.fetchval(f'SELECT uuid FROM {table} WHERE id=$1', pk)
    finally:
        await conn.close()


async def _insert_job(tenant_uuid: str, project_uuid: str, account_uuid: str, status: str) -> str:
    jid = str(uuid.uuid4())
    now = datetime.now(UTC)
    conn = await _conn()
    try:
        await conn.execute(
            """INSERT INTO delivery_job(id, tenant_id, project_id, idempotency_key, kind,
               route_id, rule_id, rule_version, account_id, source_scope, source_chat_id,
               source_message_id, revision, target_chat_id, mode, requires_approval,
               status, attempt_count, created_at, updated_at)
               VALUES($1,$2,$3,$4,'send_message','r-1','rule-1',1,$5,'s',100,200,1,300,
                      'copy',false,$6,0,$7,$7)""",
            jid,
            tenant_uuid,
            project_uuid,
            f'idem-{jid}',
            account_uuid,
            status,
            now,
        )
    finally:
        await conn.close()
    return jid


def _mk_scope(client: TestClient, headers: dict[str, str], suffix: str) -> tuple[int, int, int]:
    suffix = f'{suffix}-{uuid.uuid4().hex[:6]}'
    client.post('/tg/tenants', headers=headers, json={'name': f'投递租户{suffix}', 'status': 1})
    tid = client.get('/tg/tenants', headers=headers, params={'name': f'投递租户{suffix}'}).json()['data'][0]['id']
    client.post('/tg/projects', headers=headers, json={'name': f'投递项目{suffix}', 'tenant_id': tid, 'status': 1})
    pid = client.get('/tg/projects', headers=headers, params={'tenant_id': tid}).json()['data'][0]['id']

    async def _ins() -> int:
        conn = await _conn()
        try:
            return await conn.fetchval(
                """INSERT INTO tg_telegram_account(uuid, tenant_id, project_id,
                   phone, telegram_user_id, secret_ref, desired_status,
                   observed_status, created_time, deleted)
                   VALUES($1,$2,$3,$4,$5,'local:test','stopped','imported_quarantine',$6,0)
                   RETURNING id""",
                str(uuid.uuid4()),
                tid,
                pid,
                '254700000000',
                abs(hash(suffix)) % 10**9,
                datetime.now(UTC),
            )
        finally:
            await conn.close()

    return tid, pid, _run(_ins())


def test_delivery_query_retry_cancel(client: TestClient, token_headers: dict[str, str]) -> None:
    tid, pid, aid = _mk_scope(client, token_headers, 'D1')
    tu = _run(_fetch_uuid('tg_tenant', tid))
    pu = _run(_fetch_uuid('tg_project', pid))
    au = _run(_fetch_uuid('tg_telegram_account', aid))

    jid_ready = _run(_insert_job(tu, pu, au, 'ready'))
    jid_uncertain = _run(_insert_job(tu, pu, au, 'uncertain'))
    jid_failed = _run(_insert_job(tu, pu, au, 'failed_permanent'))

    # list:每目标状态可见
    resp = client.get('/tg/deliveries', headers=token_headers, params={'project_id': pid})
    assert resp.json()['code'] == 200
    ids = {d['id'] for d in resp.json()['data']['items']}
    assert {jid_ready, jid_uncertain, jid_failed} <= ids

    # detail(尝试记录为空数组)
    resp = client.get(f'/tg/deliveries/{jid_ready}', headers=token_headers)
    assert resp.json()['code'] == 200
    assert resp.json()['data']['attempts'] == []

    # retry:uncertain 必须走人工决策,普通重试拒绝
    resp = client.post(f'/tg/deliveries/{jid_uncertain}/retry', headers=token_headers, json={})
    assert resp.json()['code'] in (400, 500)

    # retry:ready 不可重试
    resp = client.post(f'/tg/deliveries/{jid_ready}/retry', headers=token_headers, json={})
    assert resp.json()['code'] in (400, 500)

    # retry:failed_permanent → ready
    resp = client.post(f'/tg/deliveries/{jid_failed}/retry', headers=token_headers, json={})
    assert resp.json()['code'] == 200
    job = client.get(f'/tg/deliveries/{jid_failed}', headers=token_headers).json()['data']
    assert job['status'] == 'ready'

    # cancel:ready → cancelled;幂等拒绝二次取消
    resp = client.post(f'/tg/deliveries/{jid_ready}/cancel', headers=token_headers, json={})
    assert resp.json()['code'] == 200
    job = client.get(f'/tg/deliveries/{jid_ready}', headers=token_headers).json()['data']
    assert job['status'] == 'cancelled'
    resp = client.post(f'/tg/deliveries/{jid_ready}/cancel', headers=token_headers, json={})
    assert resp.json()['code'] in (400, 500)


def test_approval_flow(client: TestClient, token_headers: dict[str, str]) -> None:
    tid, pid, aid = _mk_scope(client, token_headers, 'D2')
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

    # create candidate → 挂 pending 审批单
    resp = client.post(
        '/tg/approvals/candidates',
        headers=token_headers,
        json={
            'tenant_id': tid,
            'project_id': pid,
            'account_id': aid,
            'target_chat_id': 12345,
            'content': '回复内容',
            'content_hash': 'sha256:abc123',
            'expires_at': expires,
        },
    )
    assert resp.json()['code'] == 200, resp.text
    cand = resp.json()['data']
    assert cand['status'] == 'pending'

    approvals = client.get(
        '/tg/approvals', headers=token_headers, params={'project_id': pid, 'status': 'pending'}
    ).json()['data']
    assert len(approvals) == 1
    appr = approvals[0]
    assert appr['candidate_id'] == cand['id']
    assert appr['content_hash'] == 'sha256:abc123'

    # hash 不匹配 → 409
    resp = client.post(
        f'/tg/approvals/{appr["id"]}/approve',
        headers=token_headers,
        json={'candidate_version': 1, 'content_hash': 'sha256:WRONG'},
    )
    assert resp.json()['code'] == 409

    # version 不匹配 → 409
    resp = client.post(
        f'/tg/approvals/{appr["id"]}/approve',
        headers=token_headers,
        json={'candidate_version': 99, 'content_hash': 'sha256:abc123'},
    )
    assert resp.json()['code'] == 409

    # 正确 approve
    resp = client.post(
        f'/tg/approvals/{appr["id"]}/approve',
        headers=token_headers,
        json={'candidate_version': 1, 'content_hash': 'sha256:abc123'},
    )
    assert resp.json()['code'] == 200
    assert resp.json()['data']['status'] == 'approved'

    # 已处理不能再审
    resp = client.post(
        f'/tg/approvals/{appr["id"]}/reject',
        headers=token_headers,
        json={'candidate_version': 1, 'content_hash': 'sha256:abc123'},
    )
    assert resp.json()['code'] in (400, 500)

    # 候选状态同步 approved
    cand2 = client.get('/tg/approvals/candidates', headers=token_headers, params={'project_id': pid}).json()['data'][0]
    assert cand2['status'] == 'approved'

    # D2:审批通过 → delivery_job(ready) 落共享表,幂等键 approval:{uuid}
    async def _job_count() -> int:
        conn = await _conn()
        try:
            return await conn.fetchval(
                "SELECT count(*) FROM delivery_job WHERE idempotency_key = $1",
                f'approval:{appr["uuid"]}',
            )
        finally:
            await conn.close()

    assert _run(_job_count()) == 1
    jobs = client.get(
        '/tg/deliveries', headers=token_headers, params={'project_id': pid, 'status': 'ready'}
    ).json()['data']['items']
    assert any(j['idempotency_key'] == f'approval:{appr["uuid"]}' for j in jobs)

    # 过期审批不可通过
    resp = client.post(
        '/tg/approvals/candidates',
        headers=token_headers,
        json={
            'tenant_id': tid,
            'project_id': pid,
            'account_id': aid,
            'target_chat_id': 12345,
            'content': '过期候选',
            'content_hash': 'sha256:expired',
            'expires_at': (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
    )
    assert resp.json()['code'] == 200
    approvals2 = client.get(
        '/tg/approvals', headers=token_headers, params={'project_id': pid, 'status': 'pending'}
    ).json()['data']
    expired_appr = next(a for a in approvals2 if a['content_hash'] == 'sha256:expired')
    resp = client.post(
        f'/tg/approvals/{expired_appr["id"]}/approve',
        headers=token_headers,
        json={'candidate_version': 1, 'content_hash': 'sha256:expired'},
    )
    assert resp.json()['code'] in (400, 500)

    # reject 流
    resp = client.post(
        '/tg/approvals/candidates',
        headers=token_headers,
        json={
            'tenant_id': tid,
            'project_id': pid,
            'account_id': aid,
            'target_chat_id': 12345,
            'content': '会被拒',
            'content_hash': 'sha256:rej',
            'expires_at': expires,
        },
    )
    assert resp.json()['code'] == 200
    approvals3 = client.get(
        '/tg/approvals', headers=token_headers, params={'project_id': pid, 'status': 'pending'}
    ).json()['data']
    rej_appr = next(a for a in approvals3 if a['content_hash'] == 'sha256:rej')
    resp = client.post(
        f'/tg/approvals/{rej_appr["id"]}/reject',
        headers=token_headers,
        json={'candidate_version': 1, 'content_hash': 'sha256:rej', 'reason': '内容不合适'},
    )
    assert resp.json()['code'] == 200
    assert resp.json()['data']['status'] == 'rejected'
    assert resp.json()['data']['reason'] == '内容不合适'
