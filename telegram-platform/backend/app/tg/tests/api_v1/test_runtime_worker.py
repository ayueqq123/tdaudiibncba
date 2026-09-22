"""Worker 运行面端点:X-Worker-Token 认证 + 账号/会话/候选拉取。"""

import base64

from pathlib import Path

import pytest

from starlette.testclient import TestClient

from backend.core.conf import settings

from .test_delivery_approval import _insert_job, _mk_scope  # ruff: ignore[unused-import]


@pytest.fixture()
def worker_token(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, 'RUNTIME_WORKER_TOKEN', 'wt-test-1')
    return 'wt-test-1'


def _wheaders(token: str) -> dict[str, str]:
    return {'X-Worker-Token': token}


def test_worker_auth_rejects_bad_token(client: TestClient, worker_token: str) -> None:
    assert client.get('/tg/runtime/accounts', headers=_wheaders('wrong')).status_code in (401, 403)


def test_pull_running_accounts(
    client: TestClient, token_headers: dict[str, str], worker_token: str
) -> None:
    _tid, _pid, aid = _mk_scope(client, token_headers, 'W1')
    # 默认 stopped;改成 running 才会出现在分配清单
    client.put(f'/tg/accounts/{aid}', headers=token_headers, json={'desired_status': 'running'})
    resp = client.get('/tg/runtime/accounts', headers=_wheaders(worker_token))
    assert resp.json()['code'] == 200
    rows = resp.json()['data']
    hit = next((r for r in rows if r['id'] == aid), None)
    assert hit is not None
    assert hit['tenant_uuid'] and hit['project_uuid']


def test_pull_session_and_candidate(
    client: TestClient,
    token_headers: dict[str, str],
    worker_token: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, 'TG_IMPORT_STORAGE_DIR', str(tmp_path))
    tid, pid, aid = _mk_scope(client, token_headers, 'W2')
    client.put(f'/tg/accounts/{aid}', headers=token_headers, json={'desired_status': 'running'})
    au = client.get('/tg/accounts', headers=token_headers, params={'project_id': pid}).json()['data'][0]['uuid']

    # session:落盘文件 + meta json → base64 + app_id/app_hash
    # (_mk_scope 写入的 secret_ref 字面量为 'local:test')
    (tmp_path / 'local:test').write_bytes(b'\x01\x02sessionbytes')
    (tmp_path / 'local:test.json').write_text(
        '{"app_id": 123, "app_hash": "hh", "device": "dev"}', encoding='utf-8')
    resp = client.get(f'/tg/runtime/accounts/{au}/session', headers=_wheaders(worker_token))
    assert resp.json()['code'] == 200
    data = resp.json()['data']
    assert base64.b64decode(data['session_b64']) == b'\x01\x02sessionbytes'
    assert data['meta']['app_id'] == 123

    # candidate:经 create_candidate API 建,approve 产生 ready job,
    # worker 通过 /candidates/{uuid} 取回正文
    resp = client.post(
        '/tg/approvals/candidates', headers=token_headers,
        json={
            'tenant_id': tid, 'project_id': pid, 'account_id': aid,
            'target_chat_id': -1001, 'content': 'hello worker',
            'content_hash': __import__('hashlib').sha256(b'hello worker').hexdigest(),
            'expires_at': '2030-01-01T00:00:00Z',
        })
    assert resp.json()['code'] == 200, resp.text
    cand_uuid = resp.json()['data']['uuid']
    resp = client.get(f'/tg/runtime/candidates/{cand_uuid}', headers=_wheaders(worker_token))
    assert resp.json()['code'] == 200
    assert resp.json()['data']['content'] == 'hello worker'


def test_pull_session_not_running(client: TestClient, token_headers: dict[str, str],
                                  worker_token: str) -> None:
    _tid, pid, _aid = _mk_scope(client, token_headers, 'W3')
    au = client.get('/tg/accounts', headers=token_headers, params={'project_id': pid}).json()['data'][0]['uuid']
    resp = client.get(f'/tg/runtime/accounts/{au}/session', headers=_wheaders(worker_token))
    assert resp.json()['code'] != 200


def test_pull_rules_under_worker_token(
    client: TestClient, token_headers: dict[str, str], worker_token: str
) -> None:
    """Worker 凭证没有 request.user,拉规则不能走作用域 service——dao 直查。"""
    tid, pid, aid = _mk_scope(client, token_headers, 'W4')
    resp = client.post('/tg/clone-rules', headers=token_headers, json={
        'tenant_id': tid, 'project_id': pid, 'account_id': aid,
        'name': 'wr', 'mode': 'copy'})
    assert resp.json()['code'] == 200, resp.text
    rule = client.get(
        '/tg/clone-rules', headers=token_headers, params={'project_id': pid}
    ).json()['data'][0]
    rid = rule['id']
    assert client.post(f'/tg/clone-rules/{rid}/targets', headers=token_headers,
                       json={'source_chat_id': 1001, 'target_chat_id': 2002}).json()['code'] == 200
    assert client.post(f'/tg/clone-rules/{rid}/publish', headers=token_headers,
                       json={'expected_version': 0}).json()['code'] == 200

    resp = client.get(f'/tg/runtime/accounts/{aid}/rules', headers=_wheaders(worker_token))
    assert resp.json()['code'] == 200, resp.text
    rows = resp.json()['data']
    assert len(rows) == 1
    assert rows[0]['version'] == 1
    assert rows[0]['snapshot']['targets'][0]['source_chat_id'] == 1001
    au = client.get('/tg/accounts', headers=token_headers, params={'project_id': pid}
                    ).json()['data'][0]['uuid']
    assert rows[0]['account_uuid'] == au
