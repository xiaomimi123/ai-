"""密码哈希（pbkdf2-sha256，stdlib 自带，无新依赖）。"""
from __future__ import annotations

import hashlib
import hmac
import os

_ITER = 200_000
_ALG = "sha256"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac(_ALG, password.encode("utf-8"), salt, _ITER)
    return f"pbkdf2_{_ALG}${_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        scheme, iter_str, salt_hex, dk_hex = hashed.split("$")
        if not scheme.startswith("pbkdf2_"):
            return False
        iters = int(iter_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
    except ValueError:
        return False
    alg = scheme.split("_", 1)[1]
    dk = hashlib.pbkdf2_hmac(alg, password.encode("utf-8"), salt, iters)
    return hmac.compare_digest(dk, expected)
