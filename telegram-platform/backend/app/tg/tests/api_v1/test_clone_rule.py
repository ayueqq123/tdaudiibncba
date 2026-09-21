import io
import uuid
import zipfile

from pathlib import Path

import pytest

from starlette.testclient import TestClient

from backend.app.tg.service import account_service


def _mk_tenant_project_account(
    client: TestClient, headers: dict[str, str], suffix: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[int, int, int]:
    suffix = f'{suffix}-{uuid.uuid4().hex[:6]}'
    client.post('/tg/tenants', headers=headers, json={'name': f'规则租户{suffix}', 'status': 1})
    tid = client.get('/tg/tenants', headers=headers, params={'name': f'规则租户{suffix}'}).json()['data'][0]['id']
    client.post('/tg/projects', headers=headers, json={'name': f'规则项目{suffix}', 'tenant_id': tid, 'status': 1})
    pid = client.get('/tg/projects', headers=headers, params={'tenant_id': tid}).json()['data'][0]['id']

    async def _fake(package_path: str) -> dict:  # ruff: ignore[unused-async] — 需匹配异步签名
        sp = tmp_path / f'acc{suffix}.session'
        sp.write_bytes(b'x')
        return {
            'total': 1,
            'verified': 1,
            'results': [
                {
                    'key': f'acc{suffix}',
                    'status': 'verified',
                    'user_id': 880000 + abs(hash(suffix)) % 90000,
                    'username': 'a' + suffix,
                    'session_path': str(sp),
                }
            ],
        }

    monkeypatch.setattr(account_service, '_run_import_cli', _fake)
    monkeypatch.setattr(account_service.settings, 'TG_IMPORT_STORAGE_DIR', str(tmp_path / 'store'))

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, 'w') as zf:
        zf.writestr('a.session', b'x')
    resp = client.post(
        '/tg/accounts/import',
        headers=headers,
        data={'tenant_id': tid, 'project_id': pid},
        files={'file': ('s.zip', zbuf.getvalue(), 'application/zip')},
    )
    assert resp.json()['code'] == 200
    aid = client.get('/tg/accounts', headers=headers, params={'project_id': pid}).json()['data'][0]['id']
    return tid, pid, aid


def test_rule_publish_flow(
    client: TestClient, token_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tid, pid, aid = _mk_tenant_project_account(client, token_headers, 'R1', monkeypatch, tmp_path)

    # create rule
    resp = client.post(
        '/tg/clone-rules',
        headers=token_headers,
        json={
            'tenant_id': tid,
            'project_id': pid,
            'account_id': aid,
            'name': '规则一',
            'mode': 'copy',
        },
    )
    assert resp.json()['code'] == 200, resp.text
    rule = client.get('/tg/clone-rules', headers=token_headers, params={'project_id': pid}).json()['data'][0]
    rid = rule['id']
    assert rule['status'] == 'draft'
    assert rule['current_version'] == 0

    # publish without targets → 400
    resp = client.post(f'/tg/clone-rules/{rid}/publish', headers=token_headers, json={'expected_version': 0})
    assert resp.json()['code'] in (400, 500)

    # add target
    resp = client.post(
        f'/tg/clone-rules/{rid}/targets',
        headers=token_headers,
        json={
            'source_chat_id': 1001,
            'target_chat_id': 2002,
        },
    )
    assert resp.json()['code'] == 200, resp.text
    rule = client.get(f'/tg/clone-rules/{rid}', headers=token_headers).json()['data']
    route_id = rule['targets'][0]['route_id']

    # self-loop target rejected
    resp = client.post(
        f'/tg/clone-rules/{rid}/targets',
        headers=token_headers,
        json={
            'source_chat_id': 3003,
            'target_chat_id': 3003,
        },
    )
    assert resp.json()['code'] == 400

    # dry-run 预览
    resp = client.post(f'/tg/clone-rules/{rid}/dry-run', headers=token_headers)
    dr = resp.json()['data']
    assert dr['next_version'] == 1
    assert dr['targets'] == 1
    assert dr['problems'] == []
    assert dr['snapshot']['targets'][0]['route_id'] == route_id

    # publish 版本乐观锁
    resp = client.post(f'/tg/clone-rules/{rid}/publish', headers=token_headers, json={'expected_version': 5})
    assert resp.json()['code'] == 409
    resp = client.post(f'/tg/clone-rules/{rid}/publish', headers=token_headers, json={'expected_version': 0})
    assert resp.json()['code'] == 200
    ver = resp.json()['data']
    assert ver['version'] == 1
    assert ver['snapshot']['rule']['mode'] == 'copy'

    # 快照不可变:再发一版,旧版本仍可读
    resp = client.post(
        f'/tg/clone-rules/{rid}/targets',
        headers=token_headers,
        json={
            'source_chat_id': 1009,
            'target_chat_id': 2009,
        },
    )
    assert resp.json()['code'] == 200
    resp = client.post(f'/tg/clone-rules/{rid}/publish', headers=token_headers, json={'expected_version': 1})
    assert resp.json()['code'] == 200
    assert resp.json()['data']['version'] == 2
    assert len(resp.json()['data']['snapshot']['targets']) == 2

    # 版本历史
    resp = client.get(f'/tg/clone-rules/{rid}/versions', headers=token_headers)
    versions = resp.json()['data']
    assert [v['version'] for v in versions] == [1, 2]
    assert len(versions[0]['snapshot']['targets']) == 1  # v1 快照不变

    # worker 拉取该账号的已发布快照
    resp = client.get(f'/tg/runtime/accounts/{aid}/rules', headers=token_headers)
    pulled = resp.json()['data']
    assert len(pulled) == 1
    assert pulled[0]['version'] == 2
    assert len(pulled[0]['snapshot']['targets']) == 2

    # retire target(退役不复用)
    tid_t = client.get(f'/tg/clone-rules/{rid}', headers=token_headers).json()['data']['targets']
    target_id = tid_t[0]['id']
    resp = client.delete(f'/tg/clone-rules/{rid}/targets/{target_id}', headers=token_headers)
    assert resp.json()['code'] == 200


def test_runtime_command_flow(
    client: TestClient, token_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _tid, _pid, aid = _mk_tenant_project_account(client, token_headers, 'R2', monkeypatch, tmp_path)

    # 下发命令
    resp = client.post(
        f'/tg/runtime/accounts/{aid}/commands',
        headers=token_headers,
        json={
            'type': 'StartAccount',
            'payload': {'reason': 'test'},
        },
    )
    assert resp.json()['code'] == 200, resp.text
    cmd = resp.json()['data']
    assert cmd['status'] == 'pending'
    assert cmd['deadline'] is not None

    dedup = f'dup-{uuid.uuid4().hex[:8]}'

    # dedup 幂等:同 dedup_key 不重复下发
    resp = client.post(
        f'/tg/runtime/accounts/{aid}/commands',
        headers=token_headers,
        json={
            'type': 'StopAccount',
            'dedup_key': dedup,
        },
    )
    first = resp.json()['data']
    resp = client.post(
        f'/tg/runtime/accounts/{aid}/commands',
        headers=token_headers,
        json={
            'type': 'StopAccount',
            'dedup_key': dedup,
        },
    )
    second = resp.json()['data']
    assert first['id'] == second['id']
    assert first['dedup_key'] == dedup

    # worker 拉取 pending
    resp = client.get(f'/tg/runtime/accounts/{aid}/commands', headers=token_headers)
    pending = resp.json()['data']
    assert len(pending) == 2
    assert all(c['status'] == 'pending' for c in pending)

    # ack → done
    resp = client.post(
        f'/tg/runtime/commands/{cmd["id"]}/ack', headers=token_headers, json={'status': 'done', 'result': 'started'}
    )
    assert resp.json()['code'] == 200
    assert resp.json()['data']['status'] == 'done'
    assert resp.json()['data']['finished_at'] is not None

    # 已 done 的不再出现在 pending
    resp = client.get(f'/tg/runtime/accounts/{aid}/commands', headers=token_headers)
    assert all(c['status'] == 'pending' for c in resp.json()['data'])
    assert len(resp.json()['data']) == 1
