"""Join/resolve Telegram chats for an existing session.

CLI spawned by telegram-platform (GPL boundary: spawned, never imported).
Reads {"refs": [...]} from stdin — each ref is a numeric chat id, a public
link/username (t.me/name, @name), or an invite link (t.me/+HASH,
t.me/joinchat/HASH, tg://join?invite=HASH). Joins invite/username refs and
verifies membership for numeric ids. Prints one JSON line to stdout:

    {"ok": true, "results": {"<ref>": {"ok": true, "chat_id": -100..,
     "title": "...", "status": "member|joined"} | {"ok": false,
     "error": {"status": "..."}}}}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys

_TME_RE = re.compile(
    r'^(?:https?://)?(?:www\.)?t(?:elegram)?\.(?:me|dog)/(?P<path>.+?)/?$', re.IGNORECASE
)
_INVITE_PREFIXES = ('+', 'joinchat/')


def parse_ref(ref: str | int) -> tuple[str, str | int]:
    """Classify a chat reference → (kind, value).

    kinds: 'chat_id' | 'username' | 'invite'
    """
    if isinstance(ref, int):
        return 'chat_id', ref
    s = str(ref).strip()
    if not s:
        raise ValueError('empty ref')
    if re.fullmatch(r'-?\d+', s):
        return 'chat_id', int(s)
    if s.startswith('tg://'):
        m = re.search(r'invite=([A-Za-z0-9_-]+)', s)
        if m:
            return 'invite', m.group(1)
        raise ValueError(f'unrecognized tg link: {s}')
    m = _TME_RE.match(s)
    if m:
        path = m.group('path').lstrip('/')
        for prefix in _INVITE_PREFIXES:
            if path.startswith(prefix):
                return 'invite', path[len(prefix):].split('/')[0]
        # t.me/c/<id>/<msg> — private channel numeric link
        cm = re.match(r'^c/(\d+)', path)
        if cm:
            return 'chat_id', int('-100' + cm.group(1))
        username = path.split('/')[0]
        if username:
            return 'username', username
        raise ValueError(f'unrecognized t.me link: {s}')
    if s.startswith('@'):
        s = s[1:]
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,}', s):
        return 'username', s
    raise ValueError(f'无法识别的群标识: {s}')


def _chat_meta(entity) -> dict:
    return {
        'chat_id': int('-100' + str(entity.id)) if getattr(entity, 'broadcast', False) or getattr(entity, 'megagroup', False) else entity.id,
        'title': getattr(entity, 'title', None) or getattr(entity, 'username', None),
    }


async def _join_invite(client, invite_hash: str) -> dict:
    from telethon import errors as tg_errors
    from telethon.tl import functions

    try:
        check = await client(functions.messages.CheckChatInviteRequest(hash=invite_hash))
    except tg_errors.InviteHashExpiredError:
        return {'ok': False, 'error': {'status': 'invite_expired'}}
    except tg_errors.InviteHashInvalidError:
        return {'ok': False, 'error': {'status': 'invite_invalid'}}
    chat = getattr(check, 'chat', None)
    if chat is not None:
        return {'ok': True, **_chat_meta(chat), 'status': 'member'}
    try:
        updates = await client(functions.messages.ImportChatInviteRequest(hash=invite_hash))
    except tg_errors.UserAlreadyParticipantError:
        # already in but CheckChatInvite didn't return the chat (edge)
        chats = getattr(updates, 'chats', [])
        return {'ok': True, 'status': 'member', **(_chat_meta(chats[0]) if chats else {})}
    except tg_errors.InviteRequestSentError as exc:
        return {'ok': False, 'error': {'status': 'join_approval_pending', 'detail': str(exc)[:200]}}
    except tg_errors.InviteHashExpiredError:
        return {'ok': False, 'error': {'status': 'invite_expired'}}
    except tg_errors.FloodWaitError as exc:
        return {'ok': False, 'error': {'status': 'flood_wait', 'seconds': exc.seconds}}
    chats = getattr(updates, 'chats', [])
    return {'ok': True, 'status': 'joined', **(_chat_meta(chats[0]) if chats else {})}


async def _resolve_one(client, ref: str | int) -> dict:
    from telethon import errors as tg_errors
    from telethon.tl import functions

    try:
        kind, value = parse_ref(ref)
    except ValueError as exc:
        return {'ok': False, 'error': {'status': 'bad_ref', 'detail': str(exc)}}
    try:
        if kind == 'invite':
            return await _join_invite(client, value)
        if kind == 'username':
            try:
                updates = await client(functions.channels.JoinChannelRequest(channel=value))
            except tg_errors.UserAlreadyParticipantError:
                entity = await client.get_entity(value)
                return {'ok': True, 'status': 'member', **_chat_meta(entity)}
            except tg_errors.InviteRequestSentError as exc:
                return {'ok': False, 'error': {'status': 'join_approval_pending', 'detail': str(exc)[:200]}}
            chats = getattr(updates, 'chats', [])
            meta = _chat_meta(chats[0]) if chats else {}
            return {'ok': True, 'status': 'joined', **meta}
        entity = await client.get_entity(int(value))
        return {'ok': True, 'status': 'member', **_chat_meta(entity)}
    except tg_errors.FloodWaitError as exc:
        return {'ok': False, 'error': {'status': 'flood_wait', 'seconds': exc.seconds}}
    except Exception as exc:  # noqa: BLE001 — ValueError/not-found etc.
        status = 'not_member' if kind == 'chat_id' else 'resolve_failed'
        return {'ok': False, 'error': {'status': status, 'detail': str(exc)[:200]}}


async def _run(args) -> None:
    from telethon import TelegramClient
    from telethon.sessions import SQLiteSession

    payload = json.loads(sys.stdin.read() or '{}')
    refs = payload.get('refs') or []
    client = TelegramClient(SQLiteSession(args.session), int(args.api_id), args.api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            print(json.dumps({'ok': False, 'error': {'status': 'unauthorized'}}))
            return
        results = {}
        for ref in refs:
            results[str(ref)] = await _resolve_one(client, ref)
        print(json.dumps({'ok': True, 'results': results}))
    finally:
        await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(prog='join_chats')
    parser.add_argument('--session', required=True)
    parser.add_argument('--api-id', required=True)
    parser.add_argument('--api-hash', required=True)
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == '__main__':
    main()
