"""Локальное хранилище OTP-аккаунтов (секреты)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from core.paths import RUNTIME_DIR

from .migration import OtpAccount

STORE_PATH = RUNTIME_DIR / "otp_accounts.json"


def _account_to_dict(acc: OtpAccount) -> dict:
    return {
        "name": acc.name,
        "issuer": acc.issuer,
        "secret_b32": acc.secret_b32,
        "algorithm": acc.algorithm,
        "digits": acc.digits,
        "otp_type": acc.otp_type,
        "counter": acc.counter,
    }


def _account_from_dict(d: dict) -> OtpAccount:
    return OtpAccount(
        name=str(d.get("name") or ""),
        issuer=str(d.get("issuer") or ""),
        secret_b32=str(d["secret_b32"]),
        algorithm=str(d.get("algorithm") or "SHA1"),
        digits=int(d.get("digits") or 6),
        otp_type=str(d.get("otp_type") or "totp"),
        counter=int(d.get("counter") or 0),
    )


def _key(acc: OtpAccount) -> str:
    return f"{acc.issuer}\0{acc.name}\0{acc.secret_b32}"


def load_accounts(path: Path | None = None) -> list[OtpAccount]:
    p = path or STORE_PATH
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data.get("accounts", data if isinstance(data, list) else [])
    return [_account_from_dict(x) for x in items]


def save_accounts(accounts: Iterable[OtpAccount], path: Path | None = None) -> Path:
    p = path or STORE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "accounts": [_account_to_dict(a) for a in accounts],
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return p


def merge_accounts(
    existing: Iterable[OtpAccount],
    incoming: Iterable[OtpAccount],
) -> list[OtpAccount]:
    """Мерж по (issuer, name, secret). Новые добавляются, дубликаты пропускаются."""
    by_key: dict[str, OtpAccount] = {}
    for acc in existing:
        by_key[_key(acc)] = acc
    for acc in incoming:
        by_key[_key(acc)] = acc
    return sorted(by_key.values(), key=lambda a: a.label.lower())


def filter_accounts(
    accounts: Iterable[OtpAccount],
    query: str | None,
) -> list[OtpAccount]:
    if not query:
        return list(accounts)
    q = query.casefold()
    return [
        a
        for a in accounts
        if q in a.label.casefold()
        or q in a.issuer.casefold()
        or q in a.name.casefold()
    ]
