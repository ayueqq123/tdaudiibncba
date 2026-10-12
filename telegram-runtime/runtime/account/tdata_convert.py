"""tdata(Telegram Desktop 数据目录)→ Telethon SQLiteSession 离线转换。

架构文档 §5.1.1 TDATA 分支:
  key_datas → passcodeKey 解出 localKey → 每个账号目录的 map 文件
  → lskSelfSerialized 里的 mtpAuthorization(userId/mainDcId/各 DC authKey)
  → 写 Telethon SQLiteSession(只落主 DC 一行,与 telethon 1.44 表结构一致)。

算法按 tdesktop localstorage 文件格式实现(与 opentele td/storage.py 等价),
仅依赖 cryptg(AES-IGE)+ 标准库,不引入 PyQt。
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

from telethon.crypto import AES

TDF_MAGIC = b"TDF$"
LOCAL_KEY_SIZE = 256
WIDE_IDS_TAG = (1 << 64) - 1  # ~0,旧格式宽位标记
DC_SHIFT = 10000
LSK_SELF_SERIALIZED = 0x15
LSK_DRAFT = 0x01
LSK_DRAFT_POSITION = 0x02
LSK_LEGACY_IMAGES = 0x03
LSK_LEGACY_STICKER_IMAGES = 0x05
LSK_LEGACY_AUDIOS = 0x06
LSK_BACKGROUND_OLD_OLD = 0x08
LSK_USER_SETTINGS = 0x09
LSK_RECENT_HASHTAGS_AND_BOTS = 0x0A
LSK_STICKERS_OLD = 0x0B
LSK_SAVED_PEERS_OLD = 0x0C
LSK_REPORT_SPAM_STATUSES_OLD = 0x0D
LSK_SAVED_GIFS_OLD = 0x0E
LSK_SAVED_GIFS = 0x0F
LSK_STICKERS_KEYS = 0x10
LSK_TRUSTED_BOTS = 0x11
LSK_FAVED_STICKERS = 0x12
LSK_EXPORT_SETTINGS = 0x13
LSK_BACKGROUND_OLD = 0x14
LSK_MASKS_KEYS = 0x16
LSK_LOCATIONS = 0x04
LSK_RECENT_STICKERS_OLD = 0x07

# Telegram 生产 DC(tdesktop 内置地址;media/test 的 shifted id 取裸 id)
DC_ENDPOINTS = {
    1: ("149.154.175.53", 443),
    2: ("149.154.167.51", 443),
    3: ("149.154.175.100", 443),
    4: ("149.154.167.91", 443),
    5: ("91.108.56.130", 443),
}

# Telegram Desktop 官方内置 API 凭据——tdata 会话本来就用它登录,
# 生成的 meta 沿用,保证导入后指纹不变(换指纹是协议号被封主因)。
TDESKTOP_META = {
    "app_id": 2040,
    "app_hash": "b18441a1ff607e10a989891a5462e627",
    "device": "Desktop",
    "app_version": "tdata",
}


class TDataError(Exception):
    """tdata 解析/解密失败(结构损坏或需要本地密码)。"""


class _Stream:
    """QDataStream(Qt_5_1)最小读取子集:int 一律大端,QByteArray=u32 长度+内容。"""

    __slots__ = ("b", "pos")

    def __init__(self, data: bytes):
        self.b = data
        self.pos = 0

    def _take(self, n: int) -> bytes:
        if self.pos + n > len(self.b):
            raise TDataError(f"stream short: need {n} at {self.pos}")
        out = self.b[self.pos : self.pos + n]
        self.pos += n
        return out

    def raw(self, n: int) -> bytes:
        return self._take(n)

    def u32(self) -> int:
        return struct.unpack(">I", self._take(4))[0]

    def i32(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def u64(self) -> int:
        return struct.unpack(">Q", self._take(8))[0]

    def qbytearray(self) -> bytes:
        n = self.u32()
        if n == 0xFFFFFFFF:
            return b""
        return self._take(n)

    def at_end(self) -> bool:
        return self.pos >= len(self.b)


def _tdf_read(path: Path) -> tuple[int, bytes]:
    """TDF 文件:magic(4) + version(u32 LE) + data + md5(data|u32 len|u32 ver|magic)(16)。"""
    raw = path.read_bytes()
    if len(raw) < 24 or raw[:4] != TDF_MAGIC:
        raise TDataError("bad TDF magic")
    version = struct.unpack("<I", raw[4:8])[0]
    data, md5_stored = raw[8:-16], raw[-16:]
    md5_calc = hashlib.md5(
        data + struct.pack("<I", len(data)) + struct.pack("<I", version) + TDF_MAGIC
    ).digest()
    if md5_calc != md5_stored:
        raise TDataError("bad TDF checksum")
    return version, data


def _local_key(salt: bytes, passcode: bytes = b"") -> bytes:
    """CreateLocalKey:sha512(salt|pass|salt)→pbkdf2(无密码 1 轮,有密码 10 万轮)。"""
    inner = hashlib.sha512(salt + passcode + salt).digest()
    iters = 1 if not passcode else 100000
    return hashlib.pbkdf2_hmac("sha512", inner, salt, iters, LOCAL_KEY_SIZE)


def _aes_key_iv(key256: bytes, msg16: bytes) -> tuple[bytes, bytes]:
    """prepareAES_oldmtp(receive):x=8 的 MTProto v1 KDF。"""
    x = 8
    a = hashlib.sha1(msg16 + key256[x : x + 32]).digest()
    b = hashlib.sha1(key256[x + 32 : x + 48] + msg16 + key256[x + 48 : x + 64]).digest()
    c = hashlib.sha1(key256[x + 64 : x + 96] + msg16).digest()
    d = hashlib.sha1(msg16 + key256[x + 96 : x + 128]).digest()
    return a[:8] + b[8:20] + c[4:16], a[8:20] + b[:8] + c[16:20] + d[:8]


def _decrypt_local(encrypted: bytes, key256: bytes) -> bytes:
    """DecryptLocal:16B key128 || AES-IGE 数据;校验 sha1(plain)[:16]==key128。

    返回去掉 4B 长度前缀的载荷。"""
    if len(encrypted) <= 16 or len(encrypted) & 0x0F:
        raise TDataError(f"bad encrypted size {len(encrypted)}")
    key128, data = encrypted[:16], encrypted[16:]
    aes_key, aes_iv = _aes_key_iv(key256, key128)
    plain = AES.decrypt_ige(data, aes_key, aes_iv)
    if hashlib.sha1(plain).digest()[:16] != key128:
        raise TDataError("bad decrypt key (tdata 可能有本地密码或已损坏)")
    data_len = struct.unpack("<I", plain[:4])[0]
    if data_len > len(plain) or data_len < 4 or data_len <= len(plain) - 16:
        raise TDataError("bad decrypted size")
    return plain[4:data_len]


def _read_file(dirpath: Path, base: str) -> tuple[int, bytes]:
    """按 tdesktop 后缀优先级 s/1/0 试文件名。"""
    for suffix in ("s", "1", "0"):
        p = dirpath / f"{base}{suffix}"
        if p.exists():
            return _tdf_read(p)
    raise TDataError(f"{base}{{s,1,0}} not found")


def _read_key_datas(tdata_dir: Path, passcode: bytes) -> tuple[bytes, int]:
    """key_datas → (localKey, 账号个数)。返回 localKey 供解各账号 map。"""
    _, data = _read_file(tdata_dir, "key_data")
    st = _Stream(data)
    salt = st.qbytearray()
    key_enc = st.qbytearray()
    info_enc = st.qbytearray()
    passcode_key = _local_key(salt, passcode)
    inner = _decrypt_local(key_enc, passcode_key)
    if len(inner) < LOCAL_KEY_SIZE:
        raise TDataError("key inner data too short")
    local_key = inner[:LOCAL_KEY_SIZE]
    info = _Stream(_decrypt_local(info_enc, local_key))
    count = info.i32()
    if count <= 0:
        raise TDataError("zero accounts")
    return local_key, count


def _parse_self_serialized(blob: bytes) -> dict:
    """mtpAuthorization:userId/mainDcId + 各 DC authKey(256B)+ 待销毁 keys。"""
    st = _Stream(blob)
    user_id = st.i32()
    main_dc = st.i32()
    if ((user_id << 32) | (main_dc & 0xFFFFFFFF)) == WIDE_IDS_TAG:
        user_id = st.u64()
        main_dc = st.i32()
    keys: dict[int, bytes] = {}
    for _ in range(2):  # mtpKeys + mtpKeysToDestroy
        key_count = st.i32()
        for _ in range(key_count):
            dc_id = st.i32()
            key = st.raw(LOCAL_KEY_SIZE)
            bare = dc_id % DC_SHIFT
            keys.setdefault(bare, key)
    return {"user_id": user_id, "main_dc": main_dc, "keys": keys}


def _parse_map_payload(payload: bytes) -> dict | None:
    """扫 map 解密流里的 lsk 块,取 lskSelfSerialized。"""
    st = _Stream(payload)
    self_serialized = None
    while not st.at_end():
        key_type = st.u32()
        if key_type in (LSK_DRAFT, LSK_DRAFT_POSITION):
            count = st.u32()
            st.raw(16 * count)
        elif key_type in (LSK_LEGACY_IMAGES, LSK_LEGACY_STICKER_IMAGES, LSK_LEGACY_AUDIOS):
            count = st.u32()
            st.raw(28 * count)
        elif key_type == LSK_SELF_SERIALIZED:
            self_serialized = st.qbytearray()
        elif key_type == LSK_BACKGROUND_OLD_OLD:
            st.qbytearray()
        elif key_type in (
            LSK_LOCATIONS,
            LSK_RECENT_STICKERS_OLD,
            LSK_USER_SETTINGS,
            LSK_RECENT_HASHTAGS_AND_BOTS,
            LSK_STICKERS_OLD,
            LSK_SAVED_PEERS_OLD,
            LSK_REPORT_SPAM_STATUSES_OLD,
            LSK_SAVED_GIFS_OLD,
            LSK_SAVED_GIFS,
            LSK_TRUSTED_BOTS,
            LSK_FAVED_STICKERS,
            LSK_EXPORT_SETTINGS,
        ):
            st.u64()
        elif key_type == LSK_BACKGROUND_OLD:
            st.raw(16)
        elif key_type == LSK_STICKERS_KEYS:
            st.raw(32)
        elif key_type == LSK_MASKS_KEYS:
            st.raw(24)
        else:
            raise TDataError(f"unknown lsk block {key_type:#x}")
    if self_serialized is None:
        return None
    return _parse_self_serialized(self_serialized)


@dataclass
class TdataAccount:
    user_id: int
    main_dc: int
    keys: dict[int, bytes] = field(default_factory=dict)


def read_tdata_accounts(tdata_dir: Path, passcode: str = "") -> list[TdataAccount]:
    """解 tdata 目录 → 账号列表(按 user_id 去重,map0/map1 多代际只留一个)。"""
    local_key, _count = _read_key_datas(tdata_dir, passcode.encode())
    accounts: dict[int, TdataAccount] = {}
    for sub in sorted(tdata_dir.iterdir()):
        if not sub.is_dir():
            continue
        for cand in sorted(sub.glob("map[0-9s]")):
            try:
                _, data = _tdf_read(cand)
                st = _Stream(data)
                _legacy_salt = st.qbytearray()
                _legacy_key_enc = st.qbytearray()
                map_enc = st.qbytearray()
                parsed = _parse_map_payload(_decrypt_local(map_enc, local_key))
            except (TDataError, OSError):
                continue
            if parsed and parsed["user_id"] not in accounts:
                accounts[parsed["user_id"]] = TdataAccount(
                    user_id=parsed["user_id"],
                    main_dc=parsed["main_dc"],
                    keys=parsed["keys"],
                )
    if not accounts:
        raise TDataError("no accounts decoded (需本地密码或文件损坏)")
    return list(accounts.values())


def _write_sqlite_session(path: Path, dc_id: int, auth_key: bytes) -> None:
    from telethon.crypto import AuthKey
    from telethon.sessions import SQLiteSession

    sess = SQLiteSession(str(path))
    host, port = DC_ENDPOINTS.get(dc_id, DC_ENDPOINTS[2])
    sess.set_dc(dc_id, host, port)
    sess.auth_key = AuthKey(data=auth_key)
    sess.save()
    sess.close()


def convert_tdata(
    tdata_dir: Path,
    out_dir: Path,
    *,
    base_name: str,
    passcode: str = "",
) -> list[dict]:
    """一个 tdata 目录 → 每账号一条 {key, session_path, meta_path}。

    session/meta 写入 out_dir(与 .session+.json 协议号包同构,下游无差异)。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, acct in enumerate(read_tdata_accounts(tdata_dir, passcode)):
        key = f"{base_name}-{i}-{acct.user_id}"
        dc = acct.main_dc % DC_SHIFT
        auth_key = acct.keys.get(dc) or next(iter(acct.keys.values()), None)
        if auth_key is None:
            continue
        session_path = out_dir / f"{key}.session"
        _write_sqlite_session(session_path, dc, auth_key)
        meta = dict(TDESKTOP_META)
        meta["telegram_user_id"] = acct.user_id
        meta_path = out_dir / f"{key}.json"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        results.append({"key": key, "session_path": session_path, "meta_path": meta_path})
    return results


def find_tdata_dirs(root: Path) -> list[Path]:
    """zip 解开后找 tdata 目录:含 key_datas 文件的目录。"""
    found, seen = [], set()
    for kd in sorted(root.rglob("key_datas")):
        d = kd.parent
        if d not in seen:
            seen.add(d)
            found.append(d)
    return found
