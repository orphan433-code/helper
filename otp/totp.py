"""Генерация TOTP/HOTP кодов через pyotp."""

from __future__ import annotations

import time
from typing import Any

from .migration import OtpAccount


def _pyotp():
    try:
        import pyotp
    except ImportError as exc:
        raise ImportError("нужен pyotp: pip install pyotp") from exc
    return pyotp


def make_otp(account: OtpAccount) -> Any:
    pyotp = _pyotp()
    # pyotp принимает Base32; padding восстановит сам при необходимости
    secret = account.secret_b32
    algo = account.algorithm.upper()
    if account.otp_type == "hotp":
        return pyotp.HOTP(secret, digits=account.digits, digest=_digest(algo))
    return pyotp.TOTP(secret, digits=account.digits, digest=_digest(algo))


def _digest(algorithm: str):
    import hashlib

    mapping = {
        "SHA1": hashlib.sha1,
        "SHA256": hashlib.sha256,
        "SHA512": hashlib.sha512,
        "MD5": hashlib.md5,
    }
    return mapping.get(algorithm.upper(), hashlib.sha1)


def current_code(account: OtpAccount) -> str:
    otp = make_otp(account)
    if account.otp_type == "hotp":
        return otp.at(account.counter)
    return otp.now()


def seconds_remaining(period: int = 30) -> int:
    return period - (int(time.time()) % period)
