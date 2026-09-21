from starlette.testclient import TestClient


def _create_tenant(client: TestClient, headers: dict[str, str], name: str) -> int:
    resp = client.post('/tg/tenants', headers=headers, json={'name': name, 'status': 1})
    assert resp.json()['code'] == 200
    resp = client.get('/tg/tenants', headers=headers, params={'name': name})
    return resp.json()['data'][0]['id']


def test_project_and_membership_crud(client: TestClient, token_headers: dict[str, str]) -> None:
    tenant_id = _create_tenant(client, token_headers, '项目测试租户')

    # project create / list
    resp = client.post(
        '/tg/projects', headers=token_headers, json={'name': '项目甲', 'tenant_id': tenant_id, 'status': 1}
    )
    assert resp.json()['code'] == 200
    resp = client.get('/tg/projects', headers=token_headers, params={'tenant_id': tenant_id})
    project = resp.json()['data'][0]
    assert project['name'] == '项目甲'
    project_id = project['id']

    # membership create (admin user id = 1)
    resp = client.post(
        '/tg/memberships',
        headers=token_headers,
        json={'tenant_id': tenant_id, 'project_id': project_id, 'user_id': 1, 'role': 'owner', 'status': 1},
    )
    assert resp.json()['code'] == 200
    resp = client.get('/tg/memberships', headers=token_headers, params={'project_id': project_id})
    members = resp.json()['data']
    assert len(members) == 1
    assert members[0]['role'] == 'owner'
    membership_id = members[0]['id']

    # duplicate membership -> 409
    resp = client.post(
        '/tg/memberships',
        headers=token_headers,
        json={'tenant_id': tenant_id, 'project_id': project_id, 'user_id': 1, 'role': 'member', 'status': 1},
    )
    assert resp.json()['code'] == 409

    # membership update / delete
    resp = client.put(f'/tg/memberships/{membership_id}', headers=token_headers, json={'role': 'admin', 'status': 1})
    assert resp.json()['code'] == 200
    resp = client.delete(f'/tg/memberships/{membership_id}', headers=token_headers)
    assert resp.json()['code'] == 200

    # cleanup
    resp = client.delete(f'/tg/projects/{project_id}', headers=token_headers)
    assert resp.json()['code'] == 200
    resp = client.delete(f'/tg/tenants/{tenant_id}', headers=token_headers)
    assert resp.json()['code'] == 200


def test_project_requires_existing_tenant(client: TestClient, token_headers: dict[str, str]) -> None:
    resp = client.post(
        '/tg/projects', headers=token_headers, json={'name': '孤儿项目', 'tenant_id': 999999, 'status': 1}
    )
    assert resp.json()['code'] == 404
