"""
CLI для Google Authenticator export → локальные TOTP-коды.

Как достать QR / URI:
  1. Google Authenticator → ⋮ → Перенос аккаунтов → Экспорт
  2. Выбрать нужные аккаунты → QR на экране
  3a. Сфоткать QR другим телефоном / QR-ридером → скопировать
      строку otpauth-migration://...
  3b. Или скриншот QR → файл .png

Примеры:
  python -m otp import --uri 'otpauth-migration://offline?data=...'
  python -m otp import --image ./export.png
  python -m otp import --file ./uris.txt
  python -m otp list
  python -m otp codes
  python -m otp codes --filter bybit
  python -m otp watch --filter github
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .migration import OtpAccount, parse_migration_uri
from .qr import read_qr_texts
from .store import (
    STORE_PATH,
    filter_accounts,
    load_accounts,
    merge_accounts,
    save_accounts,
)
from .totp import current_code, seconds_remaining


def _collect_uris_from_args(args: argparse.Namespace) -> list[str]:
    uris: list[str] = []
    if args.uri:
        uris.append(args.uri)
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            uris.append(line)
    if args.image:
        uris.extend(read_qr_texts(args.image))
    if not uris and not sys.stdin.isatty():
        blob = sys.stdin.read()
        for line in blob.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                uris.append(line)
    return uris


def cmd_import(args: argparse.Namespace) -> int:
    uris = _collect_uris_from_args(args)
    if not uris:
        print(
            "нужен --uri / --file / --image или URI в stdin\n"
            "пример: python -m otp import --uri 'otpauth-migration://...'",
            file=sys.stderr,
        )
        return 2

    incoming: list[OtpAccount] = []
    for uri in uris:
        try:
            batch = parse_migration_uri(uri)
        except Exception as exc:
            print(f"ошибка разбора URI: {exc}", file=sys.stderr)
            return 1
        incoming.extend(batch)
        print(f"из URI: {len(batch)} аккаунт(ов)")

    existing = load_accounts()
    merged = merge_accounts(existing, incoming)
    path = save_accounts(merged)
    added = len(merged) - len(existing)
    print(f"сохранено: {path}")
    print(f"всего аккаунтов: {len(merged)} (новых/обновлённых ключей ≈ {max(added, 0)})")
    for acc in incoming:
        print(f"  + {acc.label}  ({acc.otp_type}, {acc.digits} digits, {acc.algorithm})")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    accounts = load_accounts()
    if not accounts:
        print(f"пусто. Сначала: python -m otp import …  (store: {STORE_PATH})")
        return 0
    for i, acc in enumerate(accounts, 1):
        print(f"{i:3}. {acc.label}  [{acc.otp_type}/{acc.algorithm}/{acc.digits}]")
    print(f"\nstore: {STORE_PATH}")
    return 0


def _print_codes(accounts: list[OtpAccount], *, show_secret: bool = False) -> None:
    left = seconds_remaining()
    print(f"осталось {left:2d}s из 30")
    print("-" * 48)
    width = max((len(a.label) for a in accounts), default=10)
    for acc in accounts:
        try:
            code = current_code(acc)
        except Exception as exc:
            code = f"ERR:{exc}"
        line = f"{acc.label:<{width}}  {code}"
        if show_secret:
            line += f"  secret={acc.secret_b32}"
        print(line)


def cmd_codes(args: argparse.Namespace) -> int:
    accounts = filter_accounts(load_accounts(), args.filter)
    if not accounts:
        print("нет аккаунтов (или фильтр пустой). import сначала.", file=sys.stderr)
        return 1
    _print_codes(accounts, show_secret=args.show_secret)
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    accounts = filter_accounts(load_accounts(), args.filter)
    if not accounts:
        print("нет аккаунтов (или фильтр пустой). import сначала.", file=sys.stderr)
        return 1
    try:
        while True:
            # clear + redraw
            sys.stdout.write("\033[2J\033[H")
            _print_codes(accounts, show_secret=args.show_secret)
            print("\nCtrl+C — выход")
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m otp",
        description="Google Authenticator export → TOTP коды",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    imp = sub.add_parser("import", help="импорт otpauth-migration URI / QR")
    imp.add_argument("--uri", help="строка otpauth-migration://...")
    imp.add_argument("--file", help="текстовый файл, URI по одному на строку")
    imp.add_argument("--image", help="скриншот/фото QR (нужен zxing-cpp)")
    imp.set_defaults(func=cmd_import)

    ls = sub.add_parser("list", help="список сохранённых аккаунтов")
    ls.set_defaults(func=cmd_list)

    codes = sub.add_parser("codes", help="текущие коды в консоль")
    codes.add_argument("--filter", "-f", help="фильтр по имени/issuer")
    codes.add_argument(
        "--show-secret",
        action="store_true",
        help="показать Base32 secret (осторожно)",
    )
    codes.set_defaults(func=cmd_codes)

    watch = sub.add_parser("watch", help="обновлять коды каждую секунду")
    watch.add_argument("--filter", "-f", help="фильтр по имени/issuer")
    watch.add_argument("--show-secret", action="store_true")
    watch.set_defaults(func=cmd_watch)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
