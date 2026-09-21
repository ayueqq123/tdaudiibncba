"""Envelope encryption: roundtrip, tamper, secret_ref binding, temp file hygiene."""

import os
import stat

import pytest

from runtime.account.session_crypto import (
    EnvelopeBlob,
    EnvelopeDecryptError,
    KeyNotFound,
    LocalKeyProvider,
    SessionEnvelope,
)

KEY1 = b"k" * 32
KEY2 = b"z" * 32


def _provider():
    return LocalKeyProvider({1: KEY1, 2: KEY2}, current=2)


def test_encrypt_decrypt_roundtrip():
    env = SessionEnvelope(_provider())
    blob = env.encrypt(b"sqlite-bytes-here", secret_ref="acct/1/session")
    plain = env.decrypt(blob, secret_ref="acct/1/session")
    assert plain == b"sqlite-bytes-here"
    # DEK is wrapped, not the plaintext key; blob holds no recoverable plaintext
    packed = blob.pack()
    assert b"sqlite-bytes-here" not in packed


def test_pack_unpack_roundtrip():
    env = SessionEnvelope(_provider())
    blob = env.encrypt(b"x" * 5000, secret_ref="ref")
    blob2 = EnvelopeBlob.unpack(blob.pack())
    assert blob2 == blob
    assert env.decrypt(blob2, secret_ref="ref") == b"x" * 5000


def test_wrong_secret_ref_fails():
    env = SessionEnvelope(_provider())
    blob = env.encrypt(b"data", secret_ref="acct/a")
    with pytest.raises(EnvelopeDecryptError):
        env.decrypt(blob, secret_ref="acct/b")


def test_wrong_key_version_fails():
    env = SessionEnvelope(_provider())
    blob = env.encrypt(b"data", secret_ref="r")
    other = SessionEnvelope(LocalKeyProvider({1: KEY1, 2: b"q" * 32}, current=2))
    with pytest.raises(EnvelopeDecryptError):
        other.decrypt(blob, secret_ref="r")


def test_missing_key_version_raises():
    env = SessionEnvelope(_provider())
    blob = env.encrypt(b"data", secret_ref="r")
    depleted = SessionEnvelope(LocalKeyProvider({1: KEY1}, current=1))
    with pytest.raises(KeyNotFound):
        depleted.decrypt(blob, secret_ref="r")


def test_local_provider_from_env():
    import base64
    env = {"TGRT_KEK_1": base64.b64encode(KEY1).decode(),
           "TGRT_KEK_3": KEY2.hex()}
    p = LocalKeyProvider.from_env(env)
    assert p.current_version() == 3
    assert p.get_key(1) == KEY1 and p.get_key(3) == KEY2


def test_materialize_and_wipe(tmp_path):
    env = SessionEnvelope(_provider())
    blob = env.encrypt(b"sessiondb", secret_ref="r")
    path = env.materialize(blob, secret_ref="r", directory=tmp_path)
    assert path.read_bytes() == b"sessiondb"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    SessionEnvelope.wipe(path)
    assert not path.exists()
    SessionEnvelope.wipe(path)  # idempotent
