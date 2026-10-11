"""tdata_convert 离线转换测试:自造加密 fixture(与解密算法互逆),
验证 key_datas→map→sqlite session 全链路,不依赖真实 tdata。"""

import hashlib
import struct
from pathlib import Path

import cryptg
import pytest

from runtime.account.tdata_convert import (
    DC_ENDPOINTS,
    LOCAL_KEY_SIZE,
    TDF_MAGIC,
    TDataError,
    _aes_key_iv,
    _local_key,
    convert_tdata,
    find_tdata_dirs,
    read_tdata_accounts,
)

LOCAL_KEY = bytes(range(256))
USER_ID = 777123456
MAIN_DC = 4
AUTH_KEYS = {2: b"k" * 256, MAIN_DC: b"a" * 256, 5: b"f" * 256}


def _enc_local(payload: bytes, key256: bytes) -> bytes:
    """PrepareEncrypted 逆实现:u32 len|payload|padding → ige(用 hash[:16] 作 key128)。"""
    data = struct.pack("<I", len(payload) + 4) + payload
    pad = (-len(data)) % 16
    data += bytes(pad)
    chk = hashlib.sha1(data).digest()[:16]
    aes_key, aes_iv = _aes_key_iv(key256, chk)
    return chk + cryptg.encrypt_ige(data, aes_key, aes_iv)


def _qb(b: bytes) -> bytes:
    return struct.pack(">I", len(b)) + b


def _tdf(payload: bytes, version: int = 3001014) -> bytes:
    md5 = hashlib.md5(
        payload + struct.pack("<I", len(payload)) + struct.pack("<I", version) + TDF_MAGIC
    ).digest()
    return TDF_MAGIC + struct.pack("<I", version) + payload + md5


def _mtp_auth_blob() -> bytes:
    out = struct.pack(">i", USER_ID) + struct.pack(">i", MAIN_DC)
    out += struct.pack(">i", len(AUTH_KEYS))
    for dc, key in AUTH_KEYS.items():
        out += struct.pack(">i", dc) + key
    out += struct.pack(">i", 0)  # keysToDestroy
    return out


def make_tdata(root: Path, passcode: bytes = b"") -> Path:
    tdata = root / "tdata"
    tdata.mkdir(parents=True)
    salt = b"S" * 32
    pass_key = _local_key(salt, passcode)
    key_enc = _enc_local(LOCAL_KEY + b"pad", pass_key)
    info = _enc_local(struct.pack(">i", 1) + struct.pack(">i", 0), LOCAL_KEY)
    (tdata / "key_datas").write_bytes(_tdf(_qb(salt) + _qb(key_enc) + _qb(info)))

    acc_dir = tdata / "D877F783D5D3EF8C"
    acc_dir.mkdir()
    map_payload = (
        struct.pack(">I", 0x04) + struct.pack(">Q", 111)  # lskLocations
        + struct.pack(">I", 0x15) + _qb(_mtp_auth_blob())  # lskSelfSerialized
        + struct.pack(">I", 0x0F) + struct.pack(">Q", 222)  # lskSavedGifs
    )
    map_enc = _enc_local(map_payload, LOCAL_KEY)
    (acc_dir / "map0").write_bytes(
        _tdf(_qb(b"L" * 32) + _qb(b"legacy") + _qb(map_enc))
    )
    return tdata


def test_find_and_read_accounts(tmp_path):
    tdata = make_tdata(tmp_path)
    assert find_tdata_dirs(tmp_path) == [tdata]
    accounts = read_tdata_accounts(tdata)
    assert len(accounts) == 1
    a = accounts[0]
    assert a.user_id == USER_ID
    assert a.main_dc == MAIN_DC
    assert a.keys[MAIN_DC] == b"a" * 256


def test_convert_writes_session_and_meta(tmp_path):
    tdata = make_tdata(tmp_path)
    out = tmp_path / "conv"
    results = convert_tdata(tdata, out, base_name="tdata")
    assert len(results) == 1
    r = results[0]
    assert r["key"] == f"tdata-0-{USER_ID}"

    from telethon.sessions import SQLiteSession

    sess = SQLiteSession(str(r["session_path"]))
    dc = sess.dc_id
    host, port = DC_ENDPOINTS[MAIN_DC]
    assert (dc, sess.server_address, sess.port) == (MAIN_DC, host, port)
    assert sess.auth_key.key == b"a" * 256
    sess.close()

    import json

    meta = json.loads(r["meta_path"].read_text())
    assert meta["app_id"] == 2040 and meta["telegram_user_id"] == USER_ID


def test_passcode_mismatch_fails(tmp_path):
    tdata = make_tdata(tmp_path, passcode=b"secret")
    with pytest.raises(TDataError):
        read_tdata_accounts(tdata)  # 空密码解不动
    accounts = read_tdata_accounts(tdata, "secret")
    assert accounts[0].user_id == USER_ID


def test_corrupt_magic(tmp_path):
    (tmp_path / "key_datas").write_bytes(b"not-a-tdf")
    with pytest.raises(TDataError):
        read_tdata_accounts(tmp_path)
