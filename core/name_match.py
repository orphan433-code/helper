"""Совпадение Account owner и Sender name (порядок слов и отчество не мешают)."""

from __future__ import annotations

import re
import unicodedata

_NON_WORD = re.compile(r"[^A-ZА-ЯЁІЇЄĞŞÇÖÜƏIİ0-9]+")
_VOWEL_RUN = re.compile(r"I{2,}")
_WORD_X = re.compile(r"\bX")
_PATRONYMIC = ("OVICH", "EVICH", "OVNA", "EVNA", "OGLY", "OGLI", "KYZY", "OGULY", "QIZI")
_FOLDS: tuple[tuple[str, str], ...] = (
    ("IYA", "IA"),
    ("IANI", "IAN"),
    ("YA", "IA"),
    ("YAN", "IAN"),
    ("YO", "IO"),
    ("YU", "IU"),
    ("YE", "E"),
    ("EY", "EI"),
    ("AY", "AI"),
    ("OY", "OI"),
    ("OLHA", "OLGA"),
    ("IOSEB", "IOSIF"),
    ("MAXIM", "MAKSIM"),
    ("PH", "P"),
    ("KH", "H"),
    ("TH", "T"),
    ("CHO", "CO"),
    ("TS", "C"),
    ("DZH", "J"),
    ("ZH", "J"),
    ("DJ", "J"),
    ("Q", "G"),
    ("SHCH", "SH"),
    ("SH", "S"),
    ("Y", "I"),
)


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(
                min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            )
        prev = cur
    return prev[-1]


def _fold(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    out = raw.upper()
    out = _NON_WORD.sub(" ", out)
    out = _WORD_X.sub("KH", out)
    for src, dst in _FOLDS:
        out = out.replace(src, dst)
    out = _VOWEL_RUN.sub("I", out)
    return " ".join(out.split())


def _stem(token: str) -> str:
    tok = token
    for suf in _PATRONYMIC:
        if tok.endswith(suf) and len(tok) > len(suf) + 2:
            base = tok[: -len(suf)]
            if len(base) <= 5:
                return base
            return tok
    return tok


def _is_patronymic(token: str) -> bool:
    return any(token.endswith(suf) for suf in _PATRONYMIC)


def _token_equiv(left: str, right: str) -> bool:
    if left == right:
        return True

    short, long_ = (left, right) if len(left) <= len(right) else (right, left)
    if len(short) >= 5 and long_.startswith(short):
        if len(long_) - len(short) <= 2:
            return True
        if len(short) <= 5 and _is_patronymic(long_):
            return True

    sl, sr = _stem(left), _stem(right)
    if sl == sr and (_is_patronymic(left) or _is_patronymic(right)):
        return True

    if len(left) == len(right) and len(left) >= 5:
        if left[1:] == right[1:] and {left[0], right[0]} == {"H", "G"}:
            return True

    if _is_patronymic(left) or _is_patronymic(right):
        return False

    dist = _lev(sl, sr)
    n = max(len(sl), len(sr))
    if n >= 10 and dist <= 2:
        return True
    if n >= 6 and dist <= 1:
        return True
    return False


def name_tokens(text: str) -> list[str]:
    return [part for part in _fold(text).split() if len(part) >= 2]


def names_match(owner: str, sender: str) -> bool:
    """True если это один человек: те же слова, порядок/отчество можно иначе."""
    left = name_tokens(owner)
    right = name_tokens(sender)
    if not left or not right:
        return False
    left_set = list(dict.fromkeys(left))
    right_set = list(dict.fromkeys(right))
    short, long_ = (
        (left_set, right_set) if len(left_set) <= len(right_set) else (right_set, left_set)
    )
    if len(short) < 2 and short != long_:
        return False
    for tok in short:
        if not any(_token_equiv(tok, other) for other in long_):
            return False
    return True
