import hashlib
import hmac
import json
import os
import time

from dataclasses import dataclass
from typing import Any

import httpx

from backend.app.tg.model.ai import TgAiBinding
from backend.common.exception import errors

HEADER_TIMESTAMP = 'X-LB-Timestamp'
HEADER_SIGNATURE = 'X-LB-Signature'
HEADER_IDEMPOTENCY = 'X-LB-Idempotency-Key'

REPLAY_WINDOW_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 15.0


def resolve_secret(secret_ref: str) -> str:
    """解析 secret_ref。首期支持 `env:<NAME>`;接 KMS 时在此扩展。"""
    if secret_ref.startswith('env:'):
        value = os.environ.get(secret_ref[4:])
        if value:
            return value
    raise errors.NotFoundError(msg=f'密钥引用无法解析: {secret_ref!r}')


def compute_signature(secret: str, body: bytes, timestamp: str | int) -> str:
    """LangBot HTTP Bot 签名:sha256=HMAC_SHA256(secret, "{ts}." + body)(D0 已核实)。"""
    signing_string = f'{timestamp}.'.encode() + body
    return f'sha256={hmac.new(secret.encode(), signing_string, hashlib.sha256).hexdigest()}'


def verify_callback_signature(
    secret: str, body: bytes, timestamp: str | None, signature: str | None
) -> tuple[bool, str]:
    """校验回调签名与时间窗(±300s)。"""
    if not timestamp or not signature:
        return False, 'missing_headers'
    try:
        ts_int = int(float(timestamp))
    except (ValueError, TypeError):
        return False, 'bad_timestamp'
    if abs(int(time.time()) - ts_int) > REPLAY_WINDOW_SECONDS:
        return False, 'expired'
    expected = compute_signature(secret, body, timestamp)
    if not hmac.compare_digest(expected, signature):
        return False, 'signature_mismatch'
    return True, ''


@dataclass
class EngineSubmitResult:
    ok: bool
    accepted_message_id: str | None = None
    status_code: int = 0
    error: str | None = None


class LangBotEngineAdapter:
    """统一引擎接口的 LangBot 实现(§9.6)。

    submit: POST {base}/bots/{bot_uuid},HMAC 签名 + Idempotency-Key。
    D0 结论:无历史注入接口 → 上下文由调用方内嵌进 message 文本。
    """

    async def submit(
        self,
        binding: TgAiBinding,
        session_id: str,
        message: list[dict[str, Any]],
        *,
        sender: dict[str, Any],
        session_type: str = 'group',
        idempotency_key: str,
    ) -> EngineSubmitResult:
        body = json.dumps(
            {
                'session_id': session_id,
                'session_type': session_type,
                'sender': sender,
                'message': message,
            }
        ).encode()
        ts = str(int(time.time()))
        headers = {
            'Content-Type': 'application/json',
            HEADER_TIMESTAMP: ts,
            HEADER_SIGNATURE: compute_signature(
                resolve_secret(binding.inbound_secret_ref), body, ts
            ),
            HEADER_IDEMPOTENCY: idempotency_key,
        }
        url = f"{binding.base_url.rstrip('/')}/bots/{binding.bot_uuid}"
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            # 结果不明 → uncertain,绝不盲目重试(§9.5)
            return EngineSubmitResult(ok=False, error=f'transport: {exc!r}')
        if resp.status_code == 202:
            data = resp.json().get('data') or {}
            return EngineSubmitResult(
                ok=True,
                accepted_message_id=data.get('accepted_message_id'),
                status_code=202,
            )
        if resp.status_code == 409:
            # 幂等冲突:平台侧须按 idempotency_key 找回原 run,不能标成功
            return EngineSubmitResult(ok=False, status_code=409, error='idempotent_conflict')
        return EngineSubmitResult(
            ok=False, status_code=resp.status_code, error=f'http_{resp.status_code}: {resp.text[:200]}'
        )

    async def reset_context(self, binding: TgAiBinding, session_id: str) -> EngineSubmitResult:
        """POST /bots/{bot_uuid}/reset — 清空 LangBot 侧会话上下文。"""
        body = json.dumps({'session_id': session_id}).encode()
        ts = str(int(time.time()))
        headers = {
            'Content-Type': 'application/json',
            HEADER_TIMESTAMP: ts,
            HEADER_SIGNATURE: compute_signature(
                resolve_secret(binding.inbound_secret_ref), body, ts
            ),
        }
        url = f"{binding.base_url.rstrip('/')}/bots/{binding.bot_uuid}/reset"
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            return EngineSubmitResult(ok=False, error=f'transport: {exc!r}')
        return EngineSubmitResult(ok=resp.status_code == 200, status_code=resp.status_code)

    async def cancel_local(self, run_id: int) -> EngineSubmitResult:
        """仅平台侧取消;不承诺远端推理停止(§9.6)。"""
        return EngineSubmitResult(ok=True)


langbot_engine_adapter = LangBotEngineAdapter()

OPENAI_TIMEOUT_SECONDS = 45.0


async def openai_complete(
    *, base_url: str, api_key: str, model: str, messages: list[dict]
) -> tuple[bool, str, str | None]:
    """OpenAI 兼容 /chat/completions 同步生成(炒群引擎,§9)。

    返回 (ok, text, error)。结果不明不盲重试:HTTPError/超时按失败处理,
    失败的 run 进 failed 态由人决定补发。
    """
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {'Authorization': f'Bearer {api_key}'}
    body = {'model': model, 'messages': messages, 'temperature': 0.8}
    try:
        async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        return False, '', f'transport: {exc!r}'
    if resp.status_code != 200:
        return False, '', f'http_{resp.status_code}: {resp.text[:200]}'
    try:
        text = (resp.json()['choices'][0]['message']['content'] or '').strip()
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return False, '', f'bad_response: {exc!r}'
    return (bool(text), text, None if text else 'empty_content')
