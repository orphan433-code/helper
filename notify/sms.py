"""
Standalone-утилита: слежка за Android-уведомлениями через dumpsys.

На Android нет iOS-пузыря autofill для SMS-кода. Код подтверждения может
прийти не как классическая SMS, а как push-уведомление какого-то
приложения (источник в форме банка подписан «Life» — оператор, не
обязательно системные «Сообщения»). Поэтому слежка идёт за ВСЕМИ pkg,
без фильтра по умолчанию — сперва нужно увидеть, откуда реально прилетает.

Читаем `dumpsys notification --noredact`, ищем новые записи (dedup по key),
пытаемся вытащить 4-значный код регуляркой из title/text.

Пока только диагностика — показывает НОВЫЕ уведомления живьём. В flow
(bank_confirm.py) пока не встроено.

Запуск:
    python sms_notify_watch.py
    python sms_notify_watch.py --pkg tj.abank.app
    python sms_notify_watch.py --poll 0.5

Ctrl+C — выход.
"""

from __future__ import annotations

import argparse
import re
import time

from device.adb import run_adb

_RECORD_RE = re.compile(r"NotificationRecord\(")
_PKG_RE = re.compile(r"\bpkg=(\S+)")
_KEY_LINE_RE = re.compile(r"^\s*key=(\S+)\s*$", re.MULTILINE)
_TITLE_RE = re.compile(r"^\s*android\.title=String\s*\((.*?)\)\s*$", re.MULTILINE)
# `when` — wall-clock epoch мс постановки уведомления (System.currentTimeMillis
# на телефоне), сравнимо напрямую с time.time()*1000 на Mac.
_WHEN_RE = re.compile(r"^\s*when=(\d+)\s*$", re.MULTILINE)
# Простые (BigTextStyle) уведомления: android.text=String (...) на одну/несколько строк.
_SIMPLE_TEXT_RE = re.compile(
    r"^\s*android\.text=String\s*\((.*?)\)\s*$\n(?:^(?!\s*android\.)(.*)$\n)*",
    re.MULTILINE,
)
# SMS-приложение (polyphone/megafon) рисует входящие SMS через MessagingStyle —
# реальный текст не в android.text (там null), а внутри android.messages Bundle:
#   [0] Bundle[{..., sender=ActivBank, text=<TEXT, может быть в несколько строк>, time=169...}]
_MESSAGING_TEXT_RE = re.compile(
    r"sender=([^,]*),\s*text=(.*?),\s*time=\d+\}\]", re.DOTALL
)
# «Код: 1234» / «Код подтверждения: 1234» / «Kod: 1234» — не путать с суммой/картой.
_CODE_RE = re.compile(
    r"(?:ваш|vash)?\s*"
    r"(?:код|kod|code|otp|пароль|parol)"
    r"(?:\s+\w+){0,3}?"
    r"\s*:?\s*"
    r"(\d{4,6})",
    re.IGNORECASE,
)
_BARE_CODE_RE = re.compile(r"^\s*(\d{4,6})\s*$")
_ACTIV_HINTS = ("activ", "life", "polyphone", "megafon")


def dump_notifications() -> str:
    proc = run_adb(["shell", "dumpsys", "notification", "--noredact"], check=False)
    return proc.stdout.decode("utf-8", errors="replace")


def _extract_text(block: str) -> str:
    """
    Реальный текст уведомления — два формата в этом дампе:
      1) MessagingStyle (SMS-приложение polyphone/megafon): текст внутри
         android.messages Bundle, sender=...,text=<...>,time=<epoch>}].
      2) BigTextStyle/обычные (напр. tj.abank.app): android.text=String (...).
    """
    m = _MESSAGING_TEXT_RE.search(block)
    if m:
        return m.group(2).strip()
    m = _SIMPLE_TEXT_RE.search(block)
    if m:
        return m.group(1).strip()
    return ""


def parse_notifications(raw: str) -> list[dict]:
    records: list[dict] = []
    starts = [m.start() for m in _RECORD_RE.finditer(raw)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(raw)
        block = raw[start:end]

        pkg_m = _PKG_RE.search(block)
        key_m = _KEY_LINE_RE.search(block)
        if pkg_m is None or key_m is None:
            continue

        title_m = _TITLE_RE.search(block)
        title = title_m.group(1).strip() if title_m else ""
        if title == "null":
            title = ""

        when_m = _WHEN_RE.search(block)
        when_ms = int(when_m.group(1)) if when_m else None

        records.append(
            {
                "pkg": pkg_m.group(1),
                "key": key_m.group(1),
                "title": title,
                "text": _extract_text(block),
                "when_ms": when_ms,
            }
        )
    return records


def _pkg_allowed(pkg: str, pkg_filter: str | None) -> bool:
    if not pkg_filter:
        return True
    needles = [p.strip().lower() for p in str(pkg_filter).split(",") if p.strip()]
    if not needles:
        return True
    hay = (pkg or "").lower()
    return any(n in hay for n in needles)


def _is_activ_source(record: dict) -> bool:
    hay = " ".join(
        str(record.get(k) or "") for k in ("pkg", "title", "text")
    ).lower()
    return any(hint in hay for hint in _ACTIV_HINTS)


def extract_code(record: dict) -> str | None:
    title = str(record.get("title") or "")
    text = str(record.get("text") or "")
    hay = f"{title}\n{text}"
    m = _CODE_RE.search(hay)
    if m:
        return m.group(1)
    if _is_activ_source(record):
        for chunk in (title, text):
            bare = _BARE_CODE_RE.match(chunk)
            if bare:
                return bare.group(1)
    return None


def snapshot_notification_keys(
    *,
    pkg_filter: str | None = None,
) -> set[str]:
    """Ключи уведомлений, уже висящих в шторке (снимок «до»)."""
    keys: set[str] = set()
    try:
        for rec in parse_notifications(dump_notifications()):
            if not _pkg_allowed(rec["pkg"], pkg_filter):
                continue
            keys.add(rec["key"])
    except Exception:
        pass
    return keys


def wait_for_sms_code(
    *,
    timeout_sec: float = 45.0,
    poll_sec: float = 0.6,
    pkg_filter: str | None = None,
    since_wall_ms: float | None = None,
    grace_sec: float = 8.0,
    baseline_keys: set[str] | None = None,
    verbose: bool = True,
) -> str:
    """
    Блокирующий poll — периодически `adb shell dumpsys notification`.

    pkg_filter: подстрока пакета или список через запятую.
    None / пусто — все pkg (Life, polyphone, megafon).

    Свежесть:
      • baseline_keys — ключи из снимка на тапе «Подтвердить» (старые не берём);
      • since_wall_ms − grace_sec — порог по when (код мог прийти до старта poll).
    Уведомления без when не отсекаем (только baseline).
    """
    import time as _time

    deadline = _time.monotonic() + timeout_sec
    threshold_ms = (since_wall_ms if since_wall_ms is not None else _time.time() * 1000)
    threshold_ms -= grace_sec * 1000
    baseline = set(baseline_keys or ())
    returned: set[str] = set()

    if verbose:
        print(
            f"    ⌨ SMS: жду код в уведомлениях (до {timeout_sec:g}с, "
            f"pkg⊇{pkg_filter!r}, baseline={len(baseline)}, "
            f"свежее {grace_sec:g}с до метки)"
        )

    while _time.monotonic() < deadline:
        records = parse_notifications(dump_notifications())
        # Свежее сперва — если пришло несколько, берём последний код.
        records.sort(key=lambda r: r.get("when_ms") or 0, reverse=True)
        for rec in records:
            key = rec["key"]
            if key in returned:
                continue
            if key in baseline:
                continue
            when_ms = rec.get("when_ms")
            if when_ms is not None and when_ms < threshold_ms:
                continue
            if not _pkg_allowed(rec["pkg"], pkg_filter):
                continue
            code = extract_code(rec)
            if code:
                returned.add(key)
                if verbose:
                    print(f"    ⌨ SMS: код {code} из уведомления pkg={rec['pkg']!r}")
                return code
            if verbose and key not in returned:
                returned.add(key)
                title = (rec.get("title") or "")[:40]
                print(
                    f"    ⌨ SMS: шторка pkg={rec['pkg']!r} "
                    f"title={title!r} — код не распознан"
                )
        _time.sleep(poll_sec)

    raise TimeoutError(
        f"Код подтверждения не пришёл в уведомлениях за {timeout_sec:g} с"
    )


def watch(
    *,
    poll_sec: float = 0.7,
    pkg_filter: str | None = None,
) -> None:
    seen: set[str] = set()

    print(
        f"[INFO] Слежу за уведомлениями (poll {poll_sec:g}с)"
        + (f", фильтр pkg⊇{pkg_filter!r}" if pkg_filter else " (все pkg — источник ещё не знаем)")
        + " — Ctrl+C для выхода"
    )

    # Стартовый снимок — уже висящие уведомления не считаем «новыми».
    for rec in parse_notifications(dump_notifications()):
        seen.add(rec["key"])
    print(f"[INFO] Стартовый снимок: {len(seen)} уведомлений (учтены как старые)")

    try:
        while True:
            records = parse_notifications(dump_notifications())
            for rec in records:
                if rec["key"] in seen:
                    continue
                seen.add(rec["key"])
                if not _pkg_allowed(rec["pkg"], pkg_filter):
                    continue

                ts = time.strftime("%H:%M:%S")
                code = extract_code(rec)
                print(f"\n[{ts}] НОВОЕ уведомление pkg={rec['pkg']!r}")
                if rec["title"]:
                    print(f"    title: {rec['title']!r}")
                if rec["text"]:
                    print(f"    text:  {rec['text']!r}")
                print(f"    → код: {code}" if code else "    → 4-значный код не найден")
            time.sleep(poll_sec)
    except KeyboardInterrupt:
        print("\n[INFO] Остановлено")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll", type=float, default=0.7, help="интервал опроса, сек")
    parser.add_argument("--pkg", type=str, default=None, help="фильтр по пакету (подстрока)")
    args = parser.parse_args()
    watch(poll_sec=args.poll, pkg_filter=args.pkg)


if __name__ == "__main__":
    main()
