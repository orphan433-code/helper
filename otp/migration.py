"""Парсер Google Authenticator export: otpauth-migration:// URI → аккаунты."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

# Wire types protobuf
_VARINT = 0
_LEN = 2

_ALGO = {0: "SHA1", 1: "SHA1", 2: "SHA256", 3: "SHA512", 4: "MD5"}
_DIGITS = {0: 6, 1: 6, 2: 8}
_OTP_TYPE = {0: "totp", 1: "hotp", 2: "totp"}


@dataclass(frozen=True)
class OtpAccount:
    name: str
    issuer: str
    secret_b32: str
    algorithm: str = "SHA1"
    digits: int = 6
    otp_type: str = "totp"
    counter: int = 0

    @property
    def label(self) -> str:
        if self.issuer and self.name:
            if self.name.startswith(f"{self.issuer}:"):
                return self.name
            return f"{self.issuer}:{self.name}"
        return self.issuer or self.name or "(unnamed)"


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7
        if shift > 70:
            raise ValueError("varint слишком длинный")
    raise ValueError("обрезанный varint")


def _read_bytes(buf: bytes, i: int) -> tuple[bytes, int]:
    length, i = _read_varint(buf, i)
    end = i + length
    if end > len(buf):
        raise ValueError("обрезанное length-delimited поле")
    return buf[i:end], end


def _parse_otp_parameters(buf: bytes) -> OtpAccount:
    secret = b""
    name = ""
    issuer = ""
    algorithm = 1
    digits = 1
    otp_type = 2
    counter = 0
    i = 0
    while i < len(buf):
        key, i = _read_varint(buf, i)
        field, wire = key >> 3, key & 7
        if field == 1 and wire == _LEN:
            secret, i = _read_bytes(buf, i)
        elif field == 2 and wire == _LEN:
            raw, i = _read_bytes(buf, i)
            name = raw.decode("utf-8", errors="replace")
        elif field == 3 and wire == _LEN:
            raw, i = _read_bytes(buf, i)
            issuer = raw.decode("utf-8", errors="replace")
        elif field == 4 and wire == _VARINT:
            algorithm, i = _read_varint(buf, i)
        elif field == 5 and wire == _VARINT:
            digits, i = _read_varint(buf, i)
        elif field == 6 and wire == _VARINT:
            otp_type, i = _read_varint(buf, i)
        elif field == 7 and wire == _VARINT:
            counter, i = _read_varint(buf, i)
        elif wire == _VARINT:
            _, i = _read_varint(buf, i)
        elif wire == _LEN:
            _, i = _read_bytes(buf, i)
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            raise ValueError(f"неизвестный wire type {wire}")

    if not secret:
        raise ValueError("в OtpParameters нет secret")

    secret_b32 = base64.b32encode(secret).decode("ascii").rstrip("=")
    return OtpAccount(
        name=name,
        issuer=issuer,
        secret_b32=secret_b32,
        algorithm=_ALGO.get(algorithm, "SHA1"),
        digits=_DIGITS.get(digits, 6),
        otp_type=_OTP_TYPE.get(otp_type, "totp"),
        counter=counter,
    )


def parse_migration_payload(raw: bytes) -> list[OtpAccount]:
    """Декод protobuf MigrationPayload → список аккаунтов."""
    accounts: list[OtpAccount] = []
    i = 0
    while i < len(raw):
        key, i = _read_varint(raw, i)
        field, wire = key >> 3, key & 7
        if field == 1 and wire == _LEN:
            chunk, i = _read_bytes(raw, i)
            accounts.append(_parse_otp_parameters(chunk))
        elif wire == _VARINT:
            _, i = _read_varint(raw, i)
        elif wire == _LEN:
            _, i = _read_bytes(raw, i)
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            raise ValueError(f"неизвестный wire type {wire}")
    return accounts


def _b64decode_padded(data: str) -> bytes:
    s = unquote(data).replace("-", "+").replace("_", "/")
    pad = (-len(s)) % 4
    return base64.b64decode(s + ("=" * pad))


def parse_migration_uri(uri: str) -> list[OtpAccount]:
    """
    Разобрать otpauth-migration://offline?data=...

    Экспорт из Google Authenticator может дать несколько QR (batch) —
    каждый URI парсится отдельно, аккаунты потом мержатся в store.
    """
    text = uri.strip()
    if not text:
        raise ValueError("пустой URI")

    # Иногда QR-ридер отдаёт только query или с пробелами/переносами
    if "otpauth-migration://" not in text and "data=" in text:
        text = "otpauth-migration://offline?" + text.split("?", 1)[-1]
    if text.startswith("otpauth-migration://") is False:
        raise ValueError(
            "ожидался otpauth-migration:// URI "
            "(экспорт Google Authenticator), получили: "
            f"{text[:80]!r}"
        )

    parsed = urlparse(text)
    qs = parse_qs(parsed.query)
    if "data" not in qs or not qs["data"]:
        raise ValueError("в URI нет параметра data=")
    raw = _b64decode_padded(qs["data"][0])
    accounts = parse_migration_payload(raw)
    if not accounts:
        raise ValueError("в migration payload нет аккаунтов")
    return accounts
