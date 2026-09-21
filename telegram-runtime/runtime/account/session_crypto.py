"""Session envelope encryption (§5.1 step 5).

Telethon SQLite session bytes are encrypted with a per-session DEK (AES-256-GCM);
the DEK is wrapped by a KEK from a pluggable provider. Business tables store only
`secret_ref` + `key_version` + the packed blob — plaintext exists only in the
owning worker's memory or a 0600 temp file it wipes on shutdown. Nothing here
logs plaintext or key material.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MAGIC = b"TGSE1"
_NONCE_LEN = 12


class KeyProvider(Protocol):
    """KEK source. Production binds KMS/HSM; tests and dev use LocalKeyProvider."""

    def current_version(self) -> int: ...
    def get_key(self, version: int) -> bytes: ...


class KeyNotFound(KeyError):
    pass


class LocalKeyProvider:
    """Dev/test KEK source: env vars TGRT_KEK / TGRT_KEK_<version>
    (base64 or hex, 32 bytes). Never use for production tenants."""

    def __init__(self, keys: dict[int, bytes] | None = None, current: int = 1):
        self._keys = dict(keys or {})
        self._current = current

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "LocalKeyProvider":
        env = env if env is not None else os.environ
        keys: dict[int, bytes] = {}
        for name, value in env.items():
            version: int | None = None
            if name == "TGRT_KEK":
                version = 1
            elif name.startswith("TGRT_KEK_") and name[9:].isdigit():
                version = int(name[9:])
            if version is None:
                continue
            keys[version] = _decode_key(value)
        if not keys:
            raise KeyNotFound("no TGRT_KEK* env vars set")
        return cls(keys, current=max(keys))

    def current_version(self) -> int:
        return self._current

    def get_key(self, version: int) -> bytes:
        try:
            return self._keys[version]
        except KeyError:
            raise KeyNotFound(f"KEK version {version} not provisioned") from None


def _decode_key(value: str) -> bytes:
    raw = value.strip()
    for decoder in (base64.b64decode, bytes.fromhex):
        try:
            key = decoder(raw)  # type: ignore[arg-type]
        except Exception:
            continue
        if len(key) == 32:
            return key
    raise ValueError("KEK must be 32 bytes (base64 or hex encoded)")


@dataclass(frozen=True)
class EnvelopeBlob:
    """Packed ciphertext. secret_ref is AAD: a blob cannot be re-bound to a
    different account/row without failing authentication."""

    key_version: int
    dek_nonce: bytes
    wrapped_dek: bytes
    data_nonce: bytes
    ciphertext: bytes

    def pack(self) -> bytes:
        header = json.dumps({
            "v": self.key_version,
            "wn": base64.b64encode(self.dek_nonce).decode(),
            "wd": base64.b64encode(self.wrapped_dek).decode(),
            "dn": base64.b64encode(self.data_nonce).decode(),
        }).encode()
        return _MAGIC + len(header).to_bytes(2, "big") + header + self.ciphertext

    @classmethod
    def unpack(cls, data: bytes) -> "EnvelopeBlob":
        if not data.startswith(_MAGIC):
            raise ValueError("not a TGSE1 envelope")
        hlen = int.from_bytes(data[5:7], "big")
        h = json.loads(data[7:7 + hlen])
        return cls(
            key_version=h["v"],
            dek_nonce=base64.b64decode(h["wn"]),
            wrapped_dek=base64.b64decode(h["wd"]),
            data_nonce=base64.b64decode(h["dn"]),
            ciphertext=data[7 + hlen:],
        )


class EnvelopeDecryptError(Exception):
    """Wrong key, wrong secret_ref binding, or corrupted blob."""


class SessionEnvelope:
    """Encrypts/decrypts session file bytes under the account's secret_ref."""

    def __init__(self, keys: KeyProvider):
        self._keys = keys

    def encrypt(self, plaintext: bytes, *, secret_ref: str) -> EnvelopeBlob:
        aad = secret_ref.encode()
        kek_version = self._keys.current_version()
        kek = AESGCM(self._keys.get_key(kek_version))
        dek = secrets.token_bytes(32)
        dek_nonce = secrets.token_bytes(_NONCE_LEN)
        data_nonce = secrets.token_bytes(_NONCE_LEN)
        return EnvelopeBlob(
            key_version=kek_version,
            dek_nonce=dek_nonce,
            wrapped_dek=kek.encrypt(dek_nonce, dek, aad),
            data_nonce=data_nonce,
            ciphertext=AESGCM(dek).encrypt(data_nonce, plaintext, aad),
        )

    def decrypt(self, blob: EnvelopeBlob, *, secret_ref: str) -> bytes:
        aad = secret_ref.encode()
        try:
            kek = AESGCM(self._keys.get_key(blob.key_version))
            dek = kek.decrypt(blob.dek_nonce, blob.wrapped_dek, aad)
            return AESGCM(dek).decrypt(blob.data_nonce, blob.ciphertext, aad)
        except (InvalidTag, ValueError) as exc:
            raise EnvelopeDecryptError("session blob fails authentication") from exc

    # -- worker-side plaintext handling -------------------------------------

    def materialize(self, blob: EnvelopeBlob, *, secret_ref: str,
                    directory: str | Path | None = None) -> Path:
        """Decrypt to a 0600 temp file for Telethon's SQLiteSession. Caller
        must pass the path to wipe() at shutdown; plaintext must never reach
        the database, logs, or durable storage."""
        data = self.decrypt(blob, secret_ref=secret_ref)
        fd, name = tempfile.mkstemp(prefix="tgsess_", suffix=".session",
                                    dir=directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except BaseException:
            os.unlink(name)
            raise
        return Path(name)

    @staticmethod
    def wipe(path: str | Path) -> None:
        """Best-effort overwrite then delete."""
        p = Path(path)
        try:
            size = p.stat().st_size
            with p.open("r+b") as f:
                f.write(b"\0" * size)
                f.flush()
                os.fsync(f.fileno())
        except FileNotFoundError:
            return
        p.unlink()
