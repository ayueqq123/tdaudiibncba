from starlette.testclient import TestClient


def test_tenant_crud(client: TestClient, token_headers: dict[str, str]) -> None:
    # create
    resp = client.post('/tg/tenants', headers=token_headers, json={'name': 'pytest租户', 'status': 1})
    assert resp.status_code == 200
    assert resp.json()['code'] == 200

    # list & detail
    resp = client.get('/tg/tenants', headers=token_headers, params={'name': 'pytest租户'})
    assert resp.status_code == 200
    items = resp.json()['data']
    assert len(items) >= 1
    pk = items[0]['id']

    resp = client.get(f'/tg/tenants/{pk}', headers=token_headers)
    assert resp.status_code == 200
    assert resp.json()['data']['name'] == 'pytest租户'

    # update
    resp = client.put(
        f'/tg/tenants/{pk}', headers=token_headers, json={'name': 'pytest租户', 'status': 0, 'remark': 'updated'}
    )
    assert resp.status_code == 200
    assert resp.json()['code'] == 200

    # delete
    resp = client.delete(f'/tg/tenants/{pk}', headers=token_headers)
    assert resp.status_code == 200
    assert resp.json()['code'] == 200

    resp = client.get(f'/tg/tenants/{pk}', headers=token_headers)
    assert resp.status_code == 404


def test_tenant_name_conflict(client: TestClient, token_headers: dict[str, str]) -> None:
    resp = client.get('/tg/tenants', headers=token_headers, params={'name': '冲突租户'})
    for item in resp.json()['data']:
        client.delete(f'/tg/tenants/{item["id"]}', headers=token_headers)

    resp = client.post('/tg/tenants', headers=token_headers, json={'name': '冲突租户', 'status': 1})
    assert resp.json()['code'] == 200
    resp = client.post('/tg/tenants', headers=token_headers, json={'name': '冲突租户', 'status': 1})
    assert resp.json()['code'] == 409

    resp = client.get('/tg/tenants', headers=token_headers, params={'name': '冲突租户'})
    for item in resp.json()['data']:
        client.delete(f'/tg/tenants/{item["id"]}', headers=token_headers)


def test_tenant_unauthorized(client: TestClient) -> None:
    resp = client.get('/tg/tenants')
    assert resp.status_code == 401
