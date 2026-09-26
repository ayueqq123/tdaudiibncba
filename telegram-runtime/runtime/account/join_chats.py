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
    from telethon import utils

    return {
        'chat_id': utils.get_peer_id(entity, add_mark=True),
        'title': getattr(entity, 'title', None) or getattr(entity, 'username', None),
    }


async def _invite_chat(client, invite_hash: str):
    """CheckChatInvite → chat object when already a participant, else None."""
    from telethon.tl import functions

    check = await client(functions.messages.CheckChatInviteRequest(hash=invite_hash))
    return getattr(check, 'chat', None)


async def _join_invite(client, invite_hash: str) -> dict:
    from telethon import errors as tg_errors
    from telethon.tl import functions

    try:
        chat = await _invite_chat(client, invite_hash)
    except tg_errors.InviteHashExpiredError:
        return {'ok': False, 'error': {'status': 'invite_expired'}}
    except tg_errors.InviteHashInvalidError:
        return {'ok': False, 'error': {'status': 'invite_invalid'}}
    if chat is not None:
        return {'ok': True, 'status': 'member', **_chat_meta(chat)}
    try:
        updates = await client(functions.messages.ImportChatInviteRequest(hash=invite_hash))
    except tg_errors.UserAlreadyParticipantError:
        updates = None
    except tg_errors.InviteRequestSentError as exc:
        return {'ok': False, 'error': {'status': 'join_approval_pending', 'detail': str(exc)[:200]}}
    except tg_errors.InviteHashExpiredError:
        return {'ok': False, 'error': {'status': 'invite_expired'}}
    except tg_errors.FloodWaitError as exc:
        return {'ok': False, 'error': {'status': 'flood_wait', 'seconds': exc.seconds}}
    chats = getattr(updates, 'chats', None) or []
    if chats:
        return {'ok': True, 'status': 'joined', **_chat_meta(chats[0])}
    # import succeeded but returned no entity — re-check invite (now a member)
    chat = await _invite_chat(client, invite_hash)
    if chat is not None:
        return {'ok': True, 'status': 'joined', **_chat_meta(chat)}
    return {'ok': False, 'error': {'status': 'resolve_failed', 'detail': 'joined but chat entity missing'}}


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
            # public group resolves by name regardless of membership
            entity = await client.get_entity(value)
            meta = _chat_meta(entity)
            try:
                await client(functions.channels.JoinChannelRequest(channel=entity))
            except tg_errors.UserAlreadyParticipantError:
                return {'ok': True, 'status': 'member', **meta}
            except tg_errors.InviteRequestSentError as exc:
                return {'ok': False, 'error': {'status': 'join_approval_pending', 'detail': str(exc)[:200]}}
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
