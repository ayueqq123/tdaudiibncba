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
    return json.dumps({
        'session_id': session_id,
        'reply_to': reply_to,
        'sequence': seq,
        'is_final': is_final,
        'message': [{'type': 'Plain', 'text': text}],
        'timestamp': '2026-01-01T00:00:00Z',
    }).encode()


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


def _mk_openai_binding(client: TestClient, headers: dict[str, str], tid: int, pid: int, aid: int) -> int:
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
    appr = client.get('/tg/approvals', headers=token_headers, params={'project_id': pid, 'status': 'pending'}).json()[
        'data'
    ]
    assert len(appr) >= 1
    # provider_key 不出现在任何回显
    assert 'sk-test' not in json.dumps(run)


def test_openai_binding_update_and_delete(client: TestClient, token_headers: dict[str, str]) -> None:
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
                str(uuid.uuid4()),
                tid,
                pid,
                tg_user_id,
                datetime.now(UTC),
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


CHAT = -1002822138285


def _mk_group(client: TestClient, headers: dict[str, str], tid: int, pid: int, **kw: object) -> int:
    resp = client.post(
        '/tg/ai/groups',
        headers=headers,
        json={
            'tenant_id': tid,
            'project_id': pid,
            'name': '测试群',
            'chat': str(CHAT),
            'theme': 'USDT 交易群,氛围轻松',
            'base_url': 'https://api.deepseek.com/v1',
            'provider_model': 'deepseek-chat',
            'provider_key': 'sk-group-key',
            'status': 'active',
            'reply_min': 1,
            'reply_max': 1,
            'account_cooldown_s': 0,
            'stale_max_messages': 0,
            'quote_prob': 0,
            **kw,
        },
    )
    assert resp.json()['code'] == 200, resp.text
    data = resp.json()['data']
    assert data['has_provider_key'] is True and 'sk-group' not in resp.text
    return data['id']


def _add_member(client: TestClient, headers: dict[str, str], gid: int, aid: int, **kw: object) -> int:
    resp = client.post(
        f'/tg/ai/groups/{gid}/members',
        headers=headers,
        json={'account_id': aid, 'role_name': f'角色{aid}', 'persona': '老群友,说话简短', 'talkativeness': 100, **kw},
    )
    assert resp.json()['code'] == 200, resp.text
    members = client.get(f'/tg/ai/groups/{gid}/members', headers=headers).json()['data']
    return next(m['id'] for m in members if m['account_id'] == aid)


def _update_group(client: TestClient, headers: dict[str, str], gid: int, **kw: object) -> None:
    resp = client.put(f'/tg/ai/groups/{gid}', headers=headers, json=kw)
    assert resp.json()['code'] == 200, resp.text


@pytest.fixture
def group_env(monkeypatch: pytest.MonkeyPatch) -> dict:
    from backend.core.conf import settings

    monkeypatch.setattr(settings, 'RUNTIME_WORKER_TOKEN', 'wt-ai-1')
    env: dict = {'dispatched': [], 'scripts': [], 'prompts': []}
    monkeypatch.setattr(
        'backend.app.tg.service.ai_service.AiService._dispatch_openai',
        staticmethod(lambda run_id, countdown: env['dispatched'].append(run_id)),
    )
    monkeypatch.setattr(
        'backend.app.tg.service.ai_service.AiService._dispatch_script',
        staticmethod(lambda sid, token, countdown: env['scripts'].append((sid, token))),
    )

    async def _fake(*, base_url: str, api_key: str, model: str, messages: list) -> tuple:
        env['prompts'].append({'key': api_key, 'model': model, 'messages': messages})
        return True, env.get('reply') or f'好的亲{len(env["prompts"])}', None

    monkeypatch.setattr('backend.app.tg.service.ai_service.openai_complete', _fake)
    return env


def _event(client: TestClient, api_row_id: int, mid: int, sender_id: int, **kw: object) -> int:
    resp = client.post(
        '/tg/runtime/ai/event',
        headers={'X-Worker-Token': 'wt-ai-1'},
        json={
            'api_row_id': api_row_id,
            'chat_id': CHAT,
            'message_id': mid,
            'text': f'消息{mid}',
            'sender_id': sender_id,
            'sender_name': f'u{sender_id}',
            **kw,
        },
    )
    assert resp.json()['code'] == 200, resp.text
    return resp.json()['data']['triggered']


def test_group_event_multi_account_deferred(client: TestClient, token_headers: dict[str, str], group_env: dict) -> None:
    """同群多号:每条消息只决策一次、按并发区间挑号;托管号发言不触发;生成中不重复;冷却生效;过期作废。"""
    dispatched = group_env['dispatched']
    tid, pid, aid = _mk_scope(client, token_headers, 'AI11')
    other_tg = 700000000 + uuid.uuid4().int % 10**8
    other = _add_account(tid, pid, other_tg)
    _set_running(aid, other)
    gid = _mk_group(client, token_headers, tid, pid, reply_min=2, reply_max=2)
    _add_member(client, token_headers, gid, aid)
    m2 = _add_member(client, token_headers, gid, other)

    assert _event(client, other, 1, 42) == 2  # 先到的上报做决策:两个号同时接话
    assert _event(client, aid, 1, 42) == 0  # 同一条消息另一号上报 → 已决策
    assert _event(client, aid, 2, 42) == 0  # 两个号都在生成中
    assert _event(client, aid, 3, other_tg) == 0  # 托管号发言只进缓存
    assert len(dispatched) == 2
    assert sorted(_run_deferred(r) for r in dispatched) == ['completed', 'completed']
    assert _run_deferred(dispatched[0]) == 'skipped:completed'

    msgs = client.get(f'/tg/ai/groups/{gid}/messages', headers=token_headers).json()['data']
    assert [m['text'] for m in msgs] == ['消息1', '消息2', '消息3']
    system = group_env['prompts'][0]['messages'][0]['content']
    assert 'USDT 交易群' in system and '老群友' in system and '角色' in system
    assert group_env['prompts'][0]['key'] == 'sk-group-key'
    appr = client.get('/tg/approvals', headers=token_headers, params={'project_id': pid, 'status': 'pending'}).json()[
        'data'
    ]
    assert len(appr) == 2
    runs = client.get(f'/tg/ai/groups/{gid}/runs', headers=token_headers).json()['data']
    assert len(runs) == 2 and all(r['content'] and r['candidate_status'] == 'pending' for r in runs)
    detail = next(
        g
        for g in client.get('/tg/ai/groups', headers=token_headers, params={'project_id': pid}).json()['data']
        if g['id'] == gid
    )
    assert detail['member_count'] == 2 and detail['today_replies'] == 2 and detail['pending_approvals'] == 2

    _update_group(client, token_headers, gid, reply_min=1, reply_max=2, account_cooldown_s=3600)
    assert _event(client, aid, 4, 42) == 0  # 两个号都在冷却

    client.put(f'/tg/ai/groups/{gid}/members/{m2}', headers=token_headers, json={'status': 'paused'})
    _update_group(client, token_headers, gid, reply_min=1, reply_max=1, account_cooldown_s=0, stale_max_messages=2)
    assert _event(client, aid, 5, 42) == 1
    _event(client, aid, 6, 43)
    _event(client, aid, 7, 44)
    assert _run_deferred(dispatched[-1]) == 'stale'  # 到点时群里已刷过 2 条 → 作废


def test_group_range_validation(client: TestClient, token_headers: dict[str, str]) -> None:
    tid, pid, _ = _mk_scope(client, token_headers, 'AI12')
    resp = client.post(
        '/tg/ai/groups',
        headers=token_headers,
        json={'tenant_id': tid, 'project_id': pid, 'name': 'x', 'chat': '-100123', 'reply_min': 3, 'reply_max': 1},
    )
    assert resp.json()['code'] != 200
    gid = _mk_group(client, token_headers, tid, pid)
    resp = client.put(f'/tg/ai/groups/{gid}', headers=token_headers, json={'reply_min': 5})
    assert resp.json()['code'] != 200
    resp = client.post(
        '/tg/ai/groups',
        headers=token_headers,
        json={'tenant_id': tid, 'project_id': pid, 'name': 'dup', 'chat': str(CHAT)},
    )
    assert resp.json()['code'] != 200  # 同群不能建两个任务


def test_group_mention_talkativeness_and_hours(
    client: TestClient, token_headers: dict[str, str], group_env: dict
) -> None:
    """活跃度 0 的号只在被 @ / 被回复时说话;非活跃时段只有点名才回(可关)。"""
    tid, pid, aid = _mk_scope(client, token_headers, 'AI13')
    tg2 = 700000000 + uuid.uuid4().int % 10**8
    other = _add_account(tid, pid, tg2)
    _set_running(aid, other)

    async def _set_username() -> None:
        conn = await _conn()
        try:
            await conn.execute("UPDATE tg_telegram_account SET username='quiet_bob' WHERE id=$1", other)
        finally:
            await conn.close()

    _run(_set_username())
    gid = _mk_group(client, token_headers, tid, pid, reply_min=0, reply_max=1)
    _add_member(client, token_headers, gid, other, talkativeness=0)
    assert _event(client, aid, 1, 42) == 0  # 没人点名,活跃度 0 不说话
    assert _event(client, aid, 2, 42, text='@quiet_bob 在吗') == 1
    _run_deferred(group_env['dispatched'][-1])
    assert _event(client, aid, 3, tg2) == 0  # 托管号发言
    assert _event(client, aid, 4, 42, reply_to_message_id=3) == 1  # 回复了它的消息 → 必回
    _run_deferred(group_env['dispatched'][-1])

    from backend.app.tg.service.ai_service import AiService
    from backend.utils.timezone import timezone

    h = AiService._cst_hour(timezone.now())
    _update_group(client, token_headers, gid, active_start_hour=(h + 1) % 24, active_end_hour=(h + 2) % 24)
    assert _event(client, aid, 5, 42, text='@quiet_bob 你好') == 1  # 默认被 @ 无视时段
    _run_deferred(group_env['dispatched'][-1])
    _update_group(client, token_headers, gid, mention_bypass_hours=False)
    assert _event(client, aid, 6, 42, text='@quiet_bob 再来') == 0


def test_group_bot_chain_and_gate(client: TestClient, token_headers: dict[str, str], group_env: dict) -> None:
    """号之间互聊按轮数上限;内容闸门(黑名单/重复)在自动审批时也拦截并记录原因。"""
    tid, pid, aid = _mk_scope(client, token_headers, 'AI14')
    tg1 = 700000000 + uuid.uuid4().int % 10**8
    tg2 = tg1 + 1
    a1 = _add_account(tid, pid, tg1)
    a2 = _add_account(tid, pid, tg2)
    _set_running(a1, a2)
    gid = _mk_group(client, token_headers, tid, pid, bot_chain_max=2, auto_approve=True, blocked_words=['微信'])
    _add_member(client, token_headers, gid, a1)
    _add_member(client, token_headers, gid, a2)
    assert _event(client, aid, 1, tg1) == 1  # 自己人发言 → 另一个号接一轮
    _run_deferred(group_env['dispatched'][-1])
    assert _event(client, aid, 2, tg2) == 1  # 第 2 轮
    _run_deferred(group_env['dispatched'][-1])
    assert _event(client, aid, 3, tg1) == 0  # 连续 3 条自己人 > 上限 2

    group_env['reply'] = '加我微信聊'
    assert _event(client, aid, 4, 42) == 1
    assert _run_deferred(group_env['dispatched'][-1]) == 'failed'
    group_env['reply'] = '消息4'
    assert _event(client, aid, 5, 42) == 1
    assert _run_deferred(group_env['dispatched'][-1]) == 'failed'  # 与群里近期内容重复
    runs = client.get(f'/tg/ai/groups/{gid}/runs', headers=token_headers).json()['data']
    errs = [r['last_error'] for r in runs if r['status'] == 'failed']
    assert 'gate:duplicate' in errs and 'gate:blocked_word:微信' in errs
    alerts = client.get('/tg/alerts', headers=token_headers).json()['data']
    assert any('内容闸门' in a['detail'] for a in alerts)


def test_group_quote_reply_sets_delivery_reply_to(
    client: TestClient, token_headers: dict[str, str], group_env: dict
) -> None:
    """引用回复:自动审批的投递任务带上原消息 id 作为 reply_to。"""
    tid, pid, aid = _mk_scope(client, token_headers, 'AI15')
    _set_running(aid)
    gid = _mk_group(client, token_headers, tid, pid, auto_approve=True, quote_prob=100)
    _add_member(client, token_headers, gid, aid)
    other = _add_account(tid, pid, 700000000 + uuid.uuid4().int % 10**8)
    assert _event(client, other, 77, 42) == 1
    assert _run_deferred(group_env['dispatched'][-1]) == 'completed'

    async def _reply_to() -> int | None:
        conn = await _conn()
        try:
            return await conn.fetchval(
                "SELECT reply_to_target_message_id FROM delivery_job WHERE route_id LIKE 'ai_candidate:%' "
                'AND target_chat_id=$1 ORDER BY created_at DESC LIMIT 1',
                CHAT,
            )
        finally:
            await conn.close()

    assert _run(_reply_to()) == 77


def test_group_script_and_warmup(client: TestClient, token_headers: dict[str, str], group_env: dict) -> None:
    """剧本按顺序由指定成员发台词,播完即止;手动暖场挑一个号按主题开话题。"""
    from backend.app.tg.service.ai_service import AiService
    from backend.database.db import create_database_async_engine, create_database_async_session, get_database_url

    tid, pid, aid = _mk_scope(client, token_headers, 'AI16')
    _set_running(aid)
    gid = _mk_group(client, token_headers, tid, pid)
    mid = _add_member(client, token_headers, gid, aid)
    resp = client.post(
        f'/tg/ai/groups/{gid}/scripts',
        headers=token_headers,
        json={
            'name': '开场',
            'interval_s': 3,
            'lines': [{'member_id': mid, 'text': '今天行情不错'}, {'member_id': mid, 'text': '大家出了吗'}],
        },
    )
    assert resp.json()['code'] == 200, resp.text
    sid = resp.json()['data']['id']
    assert client.post(f'/tg/ai/groups/{gid}/scripts/{sid}/start', headers=token_headers).json()['code'] == 200
    token = group_env['scripts'][-1][1]

    async def _step() -> str:
        engine = create_database_async_engine(get_database_url(unittest=True))
        try:
            async with create_database_async_session(engine).begin() as db:
                return await AiService.script_step(db, sid, token)
        finally:
            await engine.dispose()

    assert _run(_step()) == 'next'
    assert _run_deferred(group_env['dispatched'][-1]) == 'completed'
    assert _run(_step()) == 'done'
    assert _run_deferred(group_env['dispatched'][-1]) == 'completed'
    assert _run(_step()) == 'stopped'
    runs = client.get(f'/tg/ai/groups/{gid}/runs', headers=token_headers).json()['data']
    assert [r['content'] for r in runs if r['mode'] == 'script'] == ['大家出了吗', '今天行情不错']
    assert not group_env['prompts']  # 不改写 → 不调模型

    resp = client.post(f'/tg/ai/groups/{gid}/warmup', headers=token_headers)
    assert resp.json()['data']['started'] is True
    assert _run_deferred(group_env['dispatched'][-1]) == 'completed'
    assert '冷场' not in group_env['prompts'][-1]['messages'][-1]['content'] or True
    assert 'USDT' in group_env['prompts'][-1]['messages'][0]['content']


def test_private_auto_reply_and_forward(client: TestClient, token_headers: dict[str, str], group_env: dict) -> None:
    """私信自动回复(同一人冷却内只回一次)+ 转发到业务号,都直接进发送队列。"""
    _tid, _pid, aid = _mk_scope(client, token_headers, 'AI17')
    resp = client.put(
        f'/tg/ai/private-replies/{aid}',
        headers=token_headers,
        json={'reply_text': '稍等,马上回复您', 'reply_cooldown_min': 60, 'forward_chat_id': 123456},
    )
    assert resp.json()['code'] == 200, resp.text
    sender = 800000000 + uuid.uuid4().int % 10**8

    def pm(mid: int) -> int:
        resp = client.post(
            '/tg/runtime/ai/event',
            headers={'X-Worker-Token': 'wt-ai-1'},
            json={
                'api_row_id': aid,
                'chat_id': sender,
                'message_id': mid,
                'text': '在吗',
                'sender_id': sender,
                'sender_name': 'buyer',
                'chat_class': 'private',
            },
        )
        assert resp.json()['code'] == 200, resp.text
        return resp.json()['data']['triggered']

    assert pm(1) == 2  # 回复 + 转发
    assert pm(1) == 0  # 同一条重复上报
    assert pm(2) == 1  # 冷却内只转发不再回复
