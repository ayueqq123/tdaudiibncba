import asyncio

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.tg.service import rule_service
from backend.common.exception import errors


def test_auto_join_pool_is_best_effort_for_sender_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    account_ids = [101, 102, 103, 104, 105]
    target_ref = 't.me/private-target'
    target = SimpleNamespace(
        target_chat_id=200,
        target_chat_ref=target_ref,
        joined_account_ids=[],
        sender_status={},
    )

    class RecordingDb:
        def __init__(self) -> None:
            self.added = []

        def add(self, value: SimpleNamespace) -> None:
            self.added.append(value)

    db = RecordingDb()
    outcomes = {
        101: {'ok': True, 'chat_id': 201},
        102: {'ok': False, 'error': {'status': 'resolve_failed'}},
        103: {'ok': False, 'error': {'status': 'account_frozen'}},
    }

    def get_account(_db: RecordingDb, account_id: int) -> SimpleNamespace | None:
        return None if account_id == 105 else SimpleNamespace(id=account_id)

    def join(account: SimpleNamespace, refs: list[str]) -> dict:
        assert refs == [target_ref]
        if account.id == 104:
            raise errors.RequestError(msg='missing session credentials')
        return {target_ref: outcomes[account.id]}

    monkeypatch.setattr(rule_service.telegram_account_dao, 'get', AsyncMock(side_effect=get_account))
    monkeypatch.setattr(rule_service, 'join_chat_refs', AsyncMock(side_effect=join))

    asyncio.run(rule_service.CloneRuleService._auto_join_pool(db, account_ids, [target]))

    assert target.joined_account_ids == [101]
    assert target.target_chat_id == 201
    assert target.sender_status['101']['status'] == 'member'
    assert target.sender_status['102']['status'] == 'join_failed'
    assert target.sender_status['102']['can_post'] is False
    assert target.sender_status['102']['detail'] == rule_service.JOIN_ERR['resolve_failed']
    assert target.sender_status['103']['status'] == 'frozen'
    assert target.sender_status['103']['can_post'] is False
    assert target.sender_status['103']['detail'] == rule_service.JOIN_ERR['account_frozen']
    assert target.sender_status['104']['status'] == 'join_failed'
    assert target.sender_status['104']['can_post'] is False
    assert target.sender_status['104']['detail'] == 'missing session credentials'
    assert target.sender_status['105']['status'] == 'join_failed'
    assert target.sender_status['105']['can_post'] is False
    assert target.sender_status['105']['detail'] == '发送账号 105 不存在'
    assert len(db.added) == len(account_ids)
