"""密码哈希与 JWT 令牌（阶段 1 / `设计.md` 5.5、`开发计划.md` D01）。

密码哈希
--------
**优先 argon2**（已安装 `argon2-cffi`），**没有则回落到标准库 `hashlib.scrypt`**。
两条路径都写进同一个哈希字符串里，靠前缀区分，因此换库或调参不会让旧密码失效：

    $argon2id$v=19$m=65536,t=3,p=4$...      ← argon2-cffi 原生格式
    scrypt$n=16384,r=8,p=1$<salt_b64>$<hash_b64>   ← 标准库兜底格式

`needs_rehash()` 用于"用户下次登录时顺手升级参数/算法"。

JWT
---
- access token 短一些、refresh token 长一些（D01：30 天 / 90 天，床旁离线场景取较长有效期）。
- 令牌里带 `typ`（`access` / `refresh`），**校验时必须检查类型**，
  否则 refresh token 能被直接当 access token 用（这是一类常见漏洞）。
- refresh token 另有 `jti`，与 `auth_session.refresh_token_hash` 对应，支持吊销与轮换。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import get_settings

# --------------------------------------------------------------------------- #
# 密码哈希
# --------------------------------------------------------------------------- #

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_PREFIX = "scrypt"

try:  # pragma: no cover - 取决于环境是否装了 argon2-cffi
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerifyMismatchError
    from argon2.low_level import Type

    _ARGON2: PasswordHasher | None = PasswordHasher(
        time_cost=3, memory_cost=64 * 1024, parallelism=4, hash_len=32, salt_len=16, type=Type.ID
    )
    _ARGON2_AVAILABLE = True
except ImportError:  # pragma: no cover
    PasswordHasher = None  # type: ignore[assignment,misc]
    InvalidHashError = Exception  # type: ignore[assignment,misc]
    VerifyMismatchError = Exception  # type: ignore[assignment,misc]
    _ARGON2 = None
    _ARGON2_AVAILABLE = False


def argon2_available() -> bool:
    """当前环境是否使用 argon2（测试与健康检查会关心）。"""
    return _ARGON2_AVAILABLE


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def hash_password(password: str) -> str:
    """把明文密码变成可入库的哈希字符串。"""
    if not password:
        raise ValueError("密码不能为空")
    if _ARGON2 is not None:
        return _ARGON2.hash(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return f"{_SCRYPT_PREFIX}$n={_SCRYPT_N},r={_SCRYPT_R},p={_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def _verify_scrypt(password: str, encoded: str) -> bool:
    try:
        prefix, params, salt_b64, hash_b64 = encoded.split("$")
    except ValueError:
        return False
    if prefix != _SCRYPT_PREFIX:
        return False
    try:
        parsed = dict(item.split("=") for item in params.split(","))
        n, r, p = int(parsed["n"]), int(parsed["r"]), int(parsed["p"])
    except (KeyError, ValueError):
        return False
    # 参数可能被篡改成非法值（n 必须是 2 的幂、d 必须为正），
    # hashlib 会抛 ValueError —— 一律视为校验失败，绝不向上抛
    if n <= 1 or n & (n - 1) or r <= 0 or p <= 0:
        return False
    try:
        salt, expected = _unb64(salt_b64), _unb64(hash_b64)
    except (ValueError, TypeError):
        return False
    if not salt or not expected:
        return False
    try:
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected))
    except (ValueError, OverflowError, MemoryError):
        return False
    return hmac.compare_digest(digest, expected)


def verify_password(password: str, encoded: str | None) -> bool:
    """校验密码。**任何异常都当作校验失败**，不向上抛。

    注意：`password_hash` 允许为空（表示该账号尚未设置密码，如批量导入），
    此时一律校验失败，不能让空哈希变成"万能密码"。
    """
    if not password or not encoded:
        return False
    if encoded.startswith("$argon2"):
        if _ARGON2 is None:
            return False
        try:
            return bool(_ARGON2.verify(encoded, password))
        except (VerifyMismatchError, InvalidHashError, ValueError):
            return False
        except Exception:  # noqa: BLE001 - argon2 的异常类型随版本变化，宁失败不放行
            return False
    if encoded.startswith(f"{_SCRYPT_PREFIX}$"):
        return _verify_scrypt(password, encoded)
    return False


def needs_rehash(encoded: str | None) -> bool:
    """是否需要升级哈希（换了算法或调了参数）。"""
    if not encoded:
        return True
    if encoded.startswith("$argon2"):
        if _ARGON2 is None:
            return False
        try:
            return bool(_ARGON2.check_needs_rehash(encoded))
        except Exception:  # noqa: BLE001
            return True
    # 用的是 scrypt 兜底，而现在有 argon2 了 → 升级
    return _ARGON2 is not None


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


class TokenError(Exception):
    """令牌不合法、过期或类型不符。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class DecodedToken:
    user_id: int
    token_type: str
    expires_at: datetime
    jti: str


def _encode(user_id: int, token_type: str, ttl_seconds: int, secret: str, algorithm: str, jti: str) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": jti,
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def create_access_token(user_id: int, settings: Any | None = None) -> str:
    cfg = settings or get_settings()
    return _encode(
        user_id, TOKEN_TYPE_ACCESS, cfg.access_token_ttl_seconds, cfg.jwt_secret,
        cfg.jwt_algorithm, uuid.uuid4().hex,
    )


def create_refresh_token(user_id: int, settings: Any | None = None) -> tuple[str, str]:
    """返回 ``(token, jti)``。`jti` 要存进 `auth_session` 以便吊销。"""
    cfg = settings or get_settings()
    jti = uuid.uuid4().hex
    token = _encode(
        user_id, TOKEN_TYPE_REFRESH, cfg.refresh_token_ttl_seconds, cfg.jwt_secret,
        cfg.jwt_algorithm, jti,
    )
    return token, jti


def decode_token(token: str, expected_type: str | None = None, settings: Any | None = None) -> DecodedToken:
    """解析并校验令牌。类型不符必须拒绝。"""
    cfg = settings or get_settings()
    try:
        payload = jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("TOKEN_EXPIRED", "登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("TOKEN_INVALID", "登录凭证无效") from exc

    token_type = payload.get("typ")
    if token_type not in {TOKEN_TYPE_ACCESS, TOKEN_TYPE_REFRESH}:
        raise TokenError("TOKEN_INVALID", "登录凭证无效")
    if expected_type is not None and token_type != expected_type:
        # 拿 refresh token 当 access token 用 → 明确拒绝
        raise TokenError("TOKEN_WRONG_TYPE", f"需要 {expected_type} 令牌")

    sub = payload.get("sub")
    try:
        user_id = int(sub)
    except (TypeError, ValueError) as exc:
        raise TokenError("TOKEN_INVALID", "登录凭证无效") from exc

    exp = payload.get("exp")
    if not isinstance(exp, int):
        raise TokenError("TOKEN_INVALID", "登录凭证无效")

    return DecodedToken(
        user_id=user_id,
        token_type=str(token_type),
        expires_at=datetime.fromtimestamp(exp, tz=UTC),
        jti=str(payload.get("jti") or ""),
    )


def hash_token(token: str) -> str:
    """令牌入库前先哈希：数据库泄露也不能直接拿去冒充用户。

    令牌本身是高熵随机串，不需要加盐慢哈希，sha256 足够且更快。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


__all__ = [
    "TOKEN_TYPE_ACCESS",
    "TOKEN_TYPE_REFRESH",
    "DecodedToken",
    "TokenError",
    "argon2_available",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "hash_token",
    "needs_rehash",
    "verify_password",
]
