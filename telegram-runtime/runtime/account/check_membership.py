"""Check an account's membership/posting rights in chats.

CLI spawned by telegram-platform (GPL boundary: spawned, never imported).
Reads {"chat_ids": [...]} from stdin — numeric chat ids. For each chat the
account's own participant record is inspected. Prints one JSON line:

    {"ok": true, "results": {"-100..": {"status": "member|muted|banned|kicked|
     not_member|no_access|flood_wait|error", "can_post": true|false,
     "detail": "..."}}}
    {"ok": false, "error": {"status": "unauthorized"}}

status semantics:
  member      — in chat and allowed to post
  muted       — in chat but send_messages restricted (禁言/受限)
  banned      — ChannelParticipantBanned (封禁)
  kicked      — banned with view_messages (踢出)
  not_member  — participant not found (未在群/已退)
  no_access   — chat not resolvable/private for this account (无法访问)
  flood_wait  — rate limited; retry later
  error       — other failure (e.g. frozen account)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def _check_one(client, chat_id: int) -> dict:
    from telethon import errors as tg_errors
    from telethon.tl import functions, types

    try:
        entity = await client.get_entity(int(chat_id))
    except tg_errors.FloodWaitError as exc:
        return {'status': 'flood_wait', 'can_post': False, 'detail': f'{exc.seconds}s'}
    except Exception as exc:  # noqa: BLE001 — ChannelPrivate/ValueError: 无法访问≈不在群
        return {'status': 'no_access', 'can_post': False, 'detail': str(exc)[:200]}
    try:
        res = await client(
            functions.channels.GetParticipantRequest(
                channel=entity, participant=types.InputPeerSelf()
            )
        )
    except tg_errors.UserNotParticipantError:
        return {'status': 'not_member', 'can_post': False}
    except tg_errors.UserBannedInChannelError:
        return {'status': 'banned', 'can_post': False}
    except tg_errors.FloodWaitError as exc:
        return {'status': 'flood_wait', 'can_post': False, 'detail': f'{exc.seconds}s'}
    except Exception as exc:  # noqa: BLE001 — frozen accounts 等
        return {'status': 'error', 'can_post': False, 'detail': str(exc)[:200]}
    part = getattr(res, 'participant', None)
    if isinstance(part, types.ChannelParticipantBanned):
        rights = getattr(part, 'banned_rights', None)
        if getattr(rights, 'view_messages', False):
            return {'status': 'kicked', 'can_post': False}
        if getattr(rights, 'send_messages', False):
            return {'status': 'muted', 'can_post': False}
        return {'status': 'banned', 'can_post': False}
    default_rights = getattr(entity, 'default_banned_rights', None)
    if getattr(default_rights, 'send_messages', False):
        return {'status': 'muted', 'can_post': False, 'detail': 'group_muted'}
    return {'status': 'member', 'can_post': True}


async def _run(args) -> None:
    from telethon import TelegramClient
    from telethon.sessions import SQLiteSession

    payload = json.loads(sys.stdin.read() or '{}')
    chat_ids = payload.get('chat_ids') or []
    client = TelegramClient(SQLiteSession(args.session), int(args.api_id), args.api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            print(json.dumps({'ok': False, 'error': {'status': 'unauthorized'}}))
            return
        results = {}
        for cid in chat_ids:
            results[str(cid)] = await _check_one(client, cid)
        print(json.dumps({'ok': True, 'results': results}))
    finally:
        await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(prog='check_membership')
    parser.add_argument('--session', required=True)
    parser.add_argument('--api-id', required=True)
    parser.add_argument('--api-hash', required=True)
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == '__main__':
    main()
