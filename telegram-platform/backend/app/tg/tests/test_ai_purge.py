import asyncio

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.tg.service import ai_group_service, ai_service
from backend.common.exception import errors


def test_purge_dead_members_refreshes_and_removes_only_purgeable_states(monkeypatch: pytest.MonkeyPatch) -> None:
    group = SimpleNamespace(id=31, chat_id=9001)
    bindings = [
        SimpleNamespace(id=1, account_id=101, status='active'),
        SimpleNamespace(id=2, account_id=102, status='active'),
        SimpleNamespace(id=3, account_id=103, status='active'),
        SimpleNamespace(id=4, account_id=104, status='active'),
        SimpleNamespace(id=5, account_id=105, status='active'),
        SimpleNamespace(id=6, account_id=106, status='active'),
        SimpleNamespace(id=7, account_id=107, status='active'),
        SimpleNamespace(id=8, account_id=108, status='active'),
        SimpleNamespace(id=9, account_id=109, status='active'),
        SimpleNamespace(id=10, account_id=110, status='deleted'),
    ]
    accounts = {
        account_id: SimpleNamespace(
            id=account_id,
            username=f'user{account_id}',
            phone=None,
            telegram_user_id=account_id,
            deleted=8 if account_id == 105 else 0,
        )
        for account_id in (101, 102, 103, 104, 105, 107, 108, 109)
    }
    check_results = {
        101: {'9001': {'status': 'muted', 'detail': 'muted'}},
        102: {'9001': {'status': 'banned'}},
        103: {'9001': {'status': 'error', 'detail': 'not available for frozen accounts'}},
        104: {'__account__': {'status': 'unauthorized'}},
        107: {'9001': {'status': 'member'}},
        108: {'9001': {'status': 'not_member'}},
    }
    db = object()

    def accounts_for_members(_db: object, members: list[SimpleNamespace]) -> dict:
        assert [member.account_id for member in members] == list(range(101, 110))
        return accounts

    def check_membership(account: SimpleNamespace, chat_ids: list[int]) -> dict:
        assert chat_ids == [group.chat_id]
        if account.id == 109:
            raise errors.ServerError(msg='runtime unavailable')
        return check_results[account.id]

    get_group = AsyncMock(return_value=group)
    get_members = AsyncMock(return_value=bindings)
    fetch_accounts = AsyncMock(side_effect=accounts_for_members)
    check = AsyncMock(side_effect=check_membership)
    update_fields = AsyncMock()
    delete = AsyncMock()
    monkeypatch.setattr(ai_group_service.AiGroupService, 'get_group', get_group)
    monkeypatch.setattr(ai_group_service.AiGroupService, '_members', get_members)
    monkeypatch.setattr(ai_group_service.AiGroupService, '_accounts_for_members', fetch_accounts)
    monkeypatch.setattr(ai_service, 'check_chat_membership', check)
    monkeypatch.setattr(ai_service.ai_binding_dao, 'update_fields', update_fields)
    monkeypatch.setattr(ai_group_service.ai_binding_dao, 'delete', delete)

    result = asyncio.run(ai_group_service.AiGroupService.purge_dead_members(db=db, request=object(), pk=group.id))

    assert result.checked == 9
    assert [member.id for member in result.removed] == [1, 2, 3, 4, 5, 6]
    assert [member.state for member in result.removed] == [
        'muted',
        'banned',
        'frozen',
        'session_dead',
        'session_dead',
        'session_dead',
    ]
    assert [member.account_label for member in result.removed] == [
        '@user101',
        '@user102',
        '@user103',
        '@user104',
        '@user105',
        '-',
    ]
    assert [call.args[1] for call in delete.await_args_list] == [1, 2, 3, 4, 5, 6]
    assert {call.args[1]: call.args[2]['member_state'] for call in update_fields.await_args_list} == {
        1: 'muted',
        2: 'banned',
        3: 'frozen',
        4: 'session_dead',
        5: 'session_dead',
        6: 'session_dead',
        7: 'ok',
        8: 'not_in_group',
        9: 'check_failed',
    }
    assert check.await_count == 7


def test_purge_dead_members_handles_empty_group(monkeypatch: pytest.MonkeyPatch) -> None:
    group = SimpleNamespace(id=32, chat_id=9002)
    db = object()
    get_group = AsyncMock(return_value=group)
    get_members = AsyncMock(return_value=[])
    fetch_accounts = AsyncMock(return_value={})
    update_fields = AsyncMock()
    delete = AsyncMock()
    monkeypatch.setattr(ai_group_service.AiGroupService, 'get_group', get_group)
    monkeypatch.setattr(ai_group_service.AiGroupService, '_members', get_members)
    monkeypatch.setattr(ai_group_service.AiGroupService, '_accounts_for_members', fetch_accounts)
    monkeypatch.setattr(ai_service.ai_binding_dao, 'update_fields', update_fields)
    monkeypatch.setattr(ai_group_service.ai_binding_dao, 'delete', delete)

    result = asyncio.run(ai_group_service.AiGroupService.purge_dead_members(db=db, request=object(), pk=group.id))

    assert result.checked == 0
    assert result.removed == []
    fetch_accounts.assert_awaited_once_with(db, [])
    update_fields.assert_not_awaited()
    delete.assert_not_awaited()
