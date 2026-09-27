import asyncio
import hashlib
import hmac
import json
import time
import uuid

from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest

from starlette.testclient import TestClient

from backend.app.tg.service.ai_engine import HEADER_SIGNATURE, HEADER_TIMESTAMP

_IN_SECRET = 'test-in-secret'
_OUT_SECRET = 'test-out-secret'


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


def _sign(secret: str, body: bytes, ts: str | int) -> str:
    s = f'{ts}.'.encode() + body
    return f'sha256={hmac.new(secret.encode(), s, hashlib.sha256).hexdigest()}'


def _cb_body(session_id: str, reply_to: str, seq: int, *, is_final: bool, text: str) -> bytes:
    return json.dumps(
        {
            'session_id': session_id,
            'reply_to': reply_to,
            'sequence': seq,
            'is_final': is_final,
            'message': [{'type': 'Plain', 'text': text}],
            'timestamp': '2026-01-01T00:00:00Z',
        }
    ).encode()


def _post_cb(client: TestClient, binding_uuid: str, body: bytes, secret: str = _OUT_SECRET) -> Any:
    ts = str(int(time.time()))
    return client.post(
        f'/tg/internal/ai/langbot/{binding_uuid}/callback',
        content=body,
        headers={
            'Content-Type': 'application/json',
            HEADER_TIMESTAMP: ts,
            HEADER_SIGNATURE: _sign(secret, body, ts),
        },
    )


class _FakeEngine:
    """替代 LangBotEngineAdapter.submit:固定回 202 + accepted_message_id"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.message: list[dict[str, Any]] = []

    async def submit(self, binding: Any, session_id: str, message: Any, **kwargs: Any) -> Any:
        from backend.app.tg.service.ai_engine import EngineSubmitResult

        self.calls.append({'session_id': session_id, 'sender': kwargs.get('sender')})
        self.message = message
        return EngineSubmitResult(ok=True, accepted_message_id='in_fake001', status_code=202)

    async def reset_context(self, binding: Any, session_id: str) -> Any:
        from backend.app.tg.service.ai_engine import EngineSubmitResult

        return EngineSubmitResult(ok=True, status_code=200)


def _mk_scope(client: TestClient, headers: dict[str, str], suffix: str) -> tuple[int, int, int]:
    suffix = f'{suffix}-{uuid.uuid4().hex[:6]}'
    client.post('/tg/tenants', headers=headers, json={'name': f'AI租户{suffix}', 'status': 1})
    tid = client.get('/tg/tenants', headers=headers, params={'name': f'AI租户{suffix}'}).json()['data'][0]['id']
    client.post('/tg/projects', headers=headers, json={'name': f'AI项目{suffix}', 'tenant_id': tid, 'status': 1})
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
                '254700000001',
                abs(hash(suffix)) % 10**9,
                datetime.now(UTC),
            )
        finally:
            await conn.close()

    return tid, pid, _run(_ins())


def _mk_binding(client: TestClient, headers: dict[str, str], tid: int, pid: int, aid: int) -> tuple[int, str]:
    resp = client.post(
        '/tg/ai/bindings',
        headers=headers,
        json={
            'tenant_id': tid,
            'project_id': pid,
            'account_id': aid,
            'bot_uuid': f'bot-{uuid.uuid4().hex[:8]}',
            'base_url': 'http://langbot.test',
            'inbound_secret_ref': 'env:TEST_LB_IN',
            'outbound_secret_ref': 'env:TEST_LB_OUT',
        },
    )
    assert resp.json()['code'] == 200, resp.text
    return resp.json()['data']['id'], resp.json()['data']['uuid']


@pytest.fixture(autouse=True)
def _lb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('TEST_LB_IN', _IN_SECRET)
    monkeypatch.setenv('TEST_LB_OUT', _OUT_SECRET)


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> _FakeEngine:
    import backend.app.tg.service.ai_service as svc

    fake = _FakeEngine()
    monkeypatch.setattr(svc, 'langbot_engine_adapter', fake)
    return fake


def _trigger(client: TestClient, headers: dict[str, str], binding_id: int, chat: int = 555) -> dict:
    resp = client.post(
        '/tg/ai/runs/trigger',
        headers=headers,
        json={'binding_id': binding_id, 'chat_id': chat, 'text': '发货了吗?', 'sender_name': 'Bob'},
    )
    assert resp.json()['code'] == 200, resp.text
    return resp.json()['data']


def test_ai_trigger_and_callback_complete(
    client: TestClient, token_headers: dict[str, str], fake_engine: _FakeEngine
) -> None:
    tid, pid, aid = _mk_scope(client, token_headers, 'AI1')
    bid, buuid = _mk_binding(client, token_headers, tid, pid, aid)

    run = _trigger(client, token_headers, bid)
    assert run['status'] == 'dispatched'
    assert run['accepted_message_id'] == 'in_fake001'

    # 内嵌上下文注入(D0 结论):首条消息带 Context 块
    sent_text = fake_engine.message[0]['text']
    assert '[Context' in sent_text and '发货了吗?' in sent_text

    session_id = run['session_id']

    # seq1 非 final
    resp = _post_cb(client, buuid, _cb_body(session_id, 'in_fake001', 1, is_final=False, text='正在查…'))
    assert resp.status_code == 200
    run = client.get('/tg/ai/runs', headers=token_headers, params={'project_id': pid}).json()['data'][0]
    assert run['status'] == 'running'
    assert run['expected_seq'] == 2

    # seq2 final → 候选 + pending 审批
    resp = _post_cb(client, buuid, _cb_body(session_id, 'in_fake001', 2, is_final=True, text='明天发。'))
    assert resp.status_code == 200
    run = client.get('/tg/ai/runs', headers=token_headers, params={'project_id': pid}).json()['data'][0]
    assert run['status'] == 'completed'
    assert run['candidate_id'] is not None

    approvals = client.get(
        '/tg/approvals', headers=token_headers, params={'project_id': pid, 'status': 'pending'}
    ).json()['data']
    assert len(approvals) == 1
    assert approvals[0]['candidate_id'] == run['candidate_id']

    # 会话解锁,可再次触发
    convs = client.get('/tg/ai/conversations', headers=token_headers, params={'project_id': pid}).json()['data']
    assert convs[0]['status'] == 'open'


def test_ai_callback_dedup_and_badsig(
    client: TestClient, token_headers: dict[str, str], fake_engine: _FakeEngine
) -> None:
    tid, pid, aid = _mk_scope(client, token_headers, 'AI2')
    bid, buuid = _mk_binding(client, token_headers, tid, pid, aid)
    run = _trigger(client, token_headers, bid)
    sid = run['session_id']

    body = _cb_body(sid, 'in_fake001', 1, is_final=False, text='part1')
    assert _post_cb(client, buuid, body).status_code == 200
    # 重放同一段 → 去重(唯一键),仍 200
    resp = _post_cb(client, buuid, body)
    assert resp.status_code == 200
    assert resp.json()['result'] == 'dedup'
    # 错误密钥 → 非 2xx
    resp = _post_cb(client, buuid, body, secret='wrong')
    assert resp.status_code != 200


def test_ai_callback_gap_marks_incomplete(
    client: TestClient, token_headers: dict[str, str], fake_engine: _FakeEngine
) -> None:
    tid, pid, aid = _mk_scope(client, token_headers, 'AI3')
    bid, buuid = _mk_binding(client, token_headers, tid, pid, aid)
    run = _trigger(client, token_headers, bid)
    sid = run['session_id']

    # 直接收到 seq=2 的 final(缺 seq1)→ incomplete,不产候选
    resp = _post_cb(client, buuid, _cb_body(sid, 'in_fake001', 2, is_final=True, text='半截回复'))
    assert resp.status_code == 200
    run = client.get('/tg/ai/runs', headers=token_headers, params={'project_id': pid}).json()['data'][0]
    assert run['status'] == 'incomplete'
    assert run['candidate_id'] is None


def test_ai_single_active_run_and_cancel(
    client: TestClient, token_headers: dict[str, str], fake_engine: _FakeEngine
) -> None:
    tid, pid, aid = _mk_scope(client, token_headers, 'AI4')
    bid, _ = _mk_binding(client, token_headers, tid, pid, aid)
    run = _trigger(client, token_headers, bid)

    # 同会话并发触发 → 409
    resp = client.post(
        '/tg/ai/runs/trigger',
        headers=token_headers,
        json={'binding_id': bid, 'chat_id': 555, 'text': '再来一次'},
    )
    assert resp.json()['code'] != 200

    # 取消 → cancelled,会话解锁可再触发
    resp = client.post(f'/tg/ai/runs/{run["id"]}/cancel', headers=token_headers)
    assert resp.json()['code'] == 200
    assert resp.json()['data']['status'] == 'cancelled'
    run2 = _trigger(client, token_headers, bid)
    assert run2['status'] == 'dispatched'


def test_ai_orphan_callback_pending_link(
    client: TestClient, token_headers: dict[str, str], fake_engine: _FakeEngine
) -> None:
    tid, pid, aid = _mk_scope(client, token_headers, 'AI5')
    _bid, buuid = _mk_binding(client, token_headers, tid, pid, aid)

    # 回调先于 run 到达(未知 session)→ 落库 pending_link,不丢(§9.3)
    body = _cb_body('sess_unknown', 'in_x', 1, is_final=True, text='孤儿')
    resp = _post_cb(client, buuid, body)
    assert resp.status_code == 200
    assert resp.json()['result'] == 'ok'


async def _fake_openai(*, base_url: str, api_key: str, model: str, messages: list) -> tuple:
    return True, '好的亲,马上安排', None


def _mk_openai_binding(
    client: TestClient, headers: dict[str, str], tid: int, pid: int, aid: int
) -> int:
    resp = client.post(
        '/tg/ai/bindings',
        headers=headers,
        json={
            'tenant_id': tid,
            'project_id': pid,
            'account_id': aid,
            'engine': 'openai',
            'base_url': 'https://api.deepseek.com/v1',
            'chat_id': -1002822138285,
            'persona': '你是老群友,说话简短',
            'provider_model': 'deepseek-chat',
            'provider_key': 'sk-test-key-123',
            'speak_policy': 'all',
        },
    )
    assert resp.json()['code'] == 200, resp.text
    data = resp.json()['data']
    assert data['engine'] == 'openai'
    assert data['has_provider_key'] is True
    assert 'provider_key_enc' not in data and 'provider_key' not in data
    return data['id']


def test_openai_binding_generate_to_candidate(
    client: TestClient, token_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tid, pid, aid = _mk_scope(client, token_headers, 'AI9')
    bid = _mk_openai_binding(client, token_headers, tid, pid, aid)

    monkeypatch.setattr('backend.app.tg.service.ai_service.openai_complete', _fake_openai)
    run = _trigger(client, token_headers, bid, chat=-1002822138285)
    assert run['status'] == 'completed'
    assert run['candidate_id'] is not None

    # 直接进审批链:pending 候选已生成
    appr = client.get(
        '/tg/approvals', headers=token_headers, params={'project_id': pid, 'status': 'pending'}
    ).json()['data']
    assert len(appr) >= 1
    # provider_key 不出现在任何回显
    assert 'sk-test' not in json.dumps(run)


def test_openai_binding_update_and_delete(
    client: TestClient, token_headers: dict[str, str]
) -> None:
    tid, pid, aid = _mk_scope(client, token_headers, 'AI10')
    bid = _mk_openai_binding(client, token_headers, tid, pid, aid)

    resp = client.put(
        f'/tg/ai/bindings/{bid}',
        headers=token_headers,
        json={'status': 'paused', 'persona': '换人'},
    )
    assert resp.json()['code'] == 200
    assert resp.json()['data']['status'] == 'paused'

    resp = client.delete(f'/tg/ai/bindings/{bid}', headers=token_headers)
    assert resp.json()['code'] == 200


def _add_account(tid: int, pid: int, tg_user_id: int) -> int:
    async def _ins() -> int:
        conn = await _conn()
        try:
            return await conn.fetchval(
                """INSERT INTO tg_telegram_account(uuid, tenant_id, project_id,
                   phone, telegram_user_id, secret_ref, desired_status,
                   observed_status, created_time, deleted)
                   VALUES($1,$2,$3,'254700000001',$4,'local:test','stopped','imported_quarantine',$5,0)
                   RETURNING id""",
                str(uuid.uuid4()), tid, pid, tg_user_id, datetime.now(UTC),
            )
        finally:
            await conn.close()

    return _run(_ins())


def _run_deferred(run_id: int) -> str:
    from backend.app.tg.service.ai_service import AiService
    from backend.database.db import create_database_async_engine, create_database_async_session, get_database_url

    async def _go() -> str:
        engine = create_database_async_engine(get_database_url(unittest=True))
        try:
            async with create_database_async_session(engine).begin() as db:
                return await AiService.run_deferred_openai(db=db, run_id=run_id)
        finally:
            await engine.dispose()

    return _run(_go())


def _set_running(*ids: int) -> None:
    async def _go() -> None:
        conn = await _conn()
        try:
            await conn.execute("UPDATE tg_telegram_account SET desired_status='running' WHERE id = ANY($1)", list(ids))
        finally:
            await conn.close()

    _run(_go())


def test_group_event_multi_account_deferred(
    client: TestClient, token_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """同群多号:每条消息只决策一次、按并发区间挑号;托管号发言不触发;生成中不重复;冷却生效;延迟生成由任务执行。"""
    from backend.core.conf import settings

    monkeypatch.setattr(settings, 'RUNTIME_WORKER_TOKEN', 'wt-ai-1')
    wh = {'X-Worker-Token': 'wt-ai-1'}
    dispatched: list[int] = []
    monkeypatch.setattr(
        'backend.app.tg.service.ai_service.AiService._dispatch_openai',
        staticmethod(lambda run_id, countdown: dispatched.append(run_id)),
    )
    monkeypatch.setattr('backend.app.tg.service.ai_service.openai_complete', _fake_openai)

    tid, pid, aid = _mk_scope(client, token_headers, 'AI11')
    other_tg = 700000000 + uuid.uuid4().int % 10**8
    other = _add_account(tid, pid, other_tg)
    _set_running(aid, other)
    bid = _mk_openai_binding(client, token_headers, tid, pid, aid)
    bid2 = _mk_openai_binding(client, token_headers, tid, pid, other)
    chat = -1002822138285

    def policy(**kw: int) -> None:
        resp = client.put('/tg/ai/group-policies', headers=token_headers, json={
            'tenant_id': tid, 'project_id': pid, 'chat_id': chat, **kw})
        assert resp.json()['code'] == 200, resp.text

    def event(api_row_id: int, mid: int, sender_id: int) -> int:
        resp = client.post('/tg/runtime/ai/event', headers=wh, json={
            'api_row_id': api_row_id, 'chat_id': chat, 'message_id': mid,
            'text': f'消息{mid}', 'sender_id': sender_id, 'sender_name': f'u{sender_id}'})
        assert resp.json()['code'] == 200, resp.text
        return resp.json()['data']['triggered']

    policy(reply_min=2, reply_max=2, account_cooldown_s=0, stale_max_messages=0)
    assert event(other, 1, 42) == 2  # 先到的上报做决策:两个号同时接话
    assert event(aid, 1, 42) == 0  # 同一条消息另一号上报 → 已决策
    assert event(aid, 2, 42) == 0  # 两个号都在生成中
    assert event(aid, 3, other_tg) == 0  # 托管号发言只进缓存
    assert len(dispatched) == 2
    assert sorted(_run_deferred(r) for r in dispatched) == ['completed', 'completed']
    assert _run_deferred(dispatched[0]) == 'skipped:completed'

    async def _recent(binding_id: int) -> list:
        conn = await _conn()
        try:
            return json.loads(await conn.fetchval('SELECT recent_messages FROM tg_ai_binding WHERE id=$1', binding_id))
        finally:
            await conn.close()

    assert [m['text'] for m in _run(_recent(bid))] == ['消息1', '消息2', '消息3']
    assert [m['text'] for m in _run(_recent(bid2))] == ['消息1']
    appr = client.get('/tg/approvals', headers=token_headers,
                      params={'project_id': pid, 'status': 'pending'}).json()['data']
    assert len(appr) == 2

    policy(reply_min=1, reply_max=2, account_cooldown_s=3600)
    assert event(aid, 4, 42) == 0  # 两个号都在冷却

    client.put(f'/tg/ai/bindings/{bid2}', headers=token_headers, json={'status': 'paused'})
    policy(reply_min=1, reply_max=1, account_cooldown_s=0, stale_max_messages=2)
    assert event(aid, 5, 42) == 1
    event(aid, 6, 43)
    event(aid, 7, 44)
    assert _run_deferred(dispatched[-1]) == 'stale'  # 到点时群里已刷过 2 条 → 作废


def test_group_policy_range_validation(client: TestClient, token_headers: dict[str, str]) -> None:
    tid, pid, _ = _mk_scope(client, token_headers, 'AI12')
    resp = client.put('/tg/ai/group-policies', headers=token_headers, json={
        'tenant_id': tid, 'project_id': pid, 'chat_id': -100123, 'reply_min': 3, 'reply_max': 1})
    assert resp.json()['code'] != 200
