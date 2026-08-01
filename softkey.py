"""Ввод через UI dump: PIN-клава Activ или фокус EditText суммы."""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

from adb_device import run_adb, tap_raw, type_text_raw

_UI_DUMP_REMOTE = "/data/local/tmp/atz_ui.xml"


def _parse_bounds(raw: str) -> tuple[int, int, int, int] | None:
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw or "")
    if not m:
        return None
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def dump_ui_xml() -> str:
    run_adb(["shell", "uiautomator", "dump", _UI_DUMP_REMOTE], check=True)
    proc = run_adb(["shell", "cat", _UI_DUMP_REMOTE], check=True)
    return proc.stdout.decode("utf-8", errors="replace")


def _node_label(elem: ET.Element) -> str:
    text = (elem.attrib.get("text") or "").strip()
    if text:
        return text
    return (elem.attrib.get("content-desc") or "").strip()


def find_key_centers(xml_text: str) -> dict[str, tuple[int, int]]:
    """
    Центры кликабельных клавиш: цифры, запятая, точка.

    Activ Bank рисует PIN/сумму своими TextView (package tj.abank.app),
    не через adb input text — поэтому только тап по bounds.
    """
    root = ET.fromstring(xml_text)
    keys: dict[str, tuple[int, int]] = {}
    for elem in root.iter("node"):
        label = _node_label(elem)
        if label not in list("0123456789") and label not in (",", ".", "٫"):
            continue
        clickable = elem.attrib.get("clickable") == "true"
        # Иногда цифра в некликабельном TextView, кликабелен parent — берём bounds узла.
        bounds = _parse_bounds(elem.attrib.get("bounds", ""))
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        w, h = right - left, bottom - top
        if w < 20 or h < 20:
            continue
        # Предпочитаем clickable; некликабельные — только если клавиши ещё нет.
        ch = "," if label == "٫" else label
        cx, cy = (left + right) // 2, (top + bottom) // 2
        if ch in keys and not clickable:
            continue
        keys[ch] = (cx, cy)
    return keys


def find_action_center(xml_text: str) -> tuple[int, int] | None:
    """
    Галочка / Далее / Done только по явному text/content-desc.

    ImageView справа внизу на PIN Activ = backspace — НЕ трогаем.
    Если не нашли — вызывающий код шлёт KEYCODE_ENTER.
    """
    root = ET.fromstring(xml_text)
    for elem in root.iter("node"):
        if elem.attrib.get("clickable") != "true":
            continue
        label = _node_label(elem).lower()
        bounds = _parse_bounds(elem.attrib.get("bounds", ""))
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        if right - left < 40 or bottom - top < 40:
            continue
        if any(
            x in label
            for x in ("далее", "готово", "done", "next", "ok", "✓", "✔")
        ):
            return (left + right) // 2, (top + bottom) // 2
    return None


def type_soft_keys(
    text: str,
    *,
    gap_sec: float = 0.12,
    verbose: bool = True,
    refresh_every: int = 0,
) -> None:
    """
    Ввод строки тапами по кнопкам из uiautomator dump.

    refresh_every: 0 = один dump на всю строку; N = обновлять каждые N символов.
    """
    if not text:
        return

    xml_text = dump_ui_xml()
    keys = find_key_centers(xml_text)
    if verbose:
        found = "".join(sorted(keys))
        print(f"    ⌨ softkey UI: найдены клавиши [{found}]")

    typed = 0
    for ch in text:
        if refresh_every and typed > 0 and typed % refresh_every == 0:
            xml_text = dump_ui_xml()
            keys = find_key_centers(xml_text)

        if ch not in keys:
            # Один повторный dump — клава могла дорисоваться
            xml_text = dump_ui_xml()
            keys = find_key_centers(xml_text)
        if ch not in keys:
            raise RuntimeError(
                f"softkey: нет кнопки {ch!r} на экране "
                f"(есть: {sorted(keys)}). Открой поле суммы с цифровой клавой."
            )
        x, y = keys[ch]
        if verbose:
            print(f"    ⌨ softkey tap {ch!r} @ ({x}, {y})")
        tap_raw(x, y)
        typed += 1
        if gap_sec > 0:
            time.sleep(gap_sec)


def find_amount_edit_tap(xml_text: str) -> tuple[int, int] | None:
    """
    Центр тапа по EditText суммы — слева, подальше от TJS справа.

    В dump пустое поле часто имеет text=\"Сумма\".
    """
    root = ET.fromstring(xml_text)
    amount_nodes: list[tuple[int, int, int, int, str]] = []
    tjs_left: int | None = None

    for elem in root.iter("node"):
        cls = elem.attrib.get("class") or ""
        label = _node_label(elem)
        bounds = _parse_bounds(elem.attrib.get("bounds", ""))
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        if label == "TJS" and "TextView" in cls:
            tjs_left = left if tjs_left is None else min(tjs_left, left)
        if "EditText" not in cls:
            continue
        # Плейсхолдер «Сумма» или уже введённое число
        looks_amount = label == "Сумма" or bool(
            re.fullmatch(r"\d+[.,]\d{2}", label or "")
        )
        if looks_amount:
            amount_nodes.append((left, top, right, bottom, label))

    if not amount_nodes and tjs_left is not None:
        # Fallback: EditText сразу левее TJS на той же высоте
        for elem in root.iter("node"):
            if "EditText" not in (elem.attrib.get("class") or ""):
                continue
            bounds = _parse_bounds(elem.attrib.get("bounds", ""))
            if bounds is None:
                continue
            left, top, right, bottom = bounds
            if right <= tjs_left and abs(((top + bottom) / 2) - 0) >= 0:
                # примерно одна линия с TJS — возьмём ближайший по Y позже
                amount_nodes.append((left, top, right, bottom, _node_label(elem)))

    if not amount_nodes:
        return None

    # Предпочитаем явный «Сумма»
    amount_nodes.sort(key=lambda n: (0 if n[4] == "Сумма" else 1, n[1]))
    left, top, right, bottom, _ = amount_nodes[0]
    # Тап в левой трети поля — не задеть TJS
    cx = left + max(int((right - left) * 0.35), 12)
    cy = (top + bottom) // 2
    return cx, cy


def find_any_edit_tap(xml_text: str) -> tuple[int, int] | None:
    """
    Первый видимый EditText на экране — для полей без привязки к «Сумма»
    (SMS-код и т.п.). Берём самый верхний (наименьший top), если их несколько.
    """
    root = ET.fromstring(xml_text)
    candidates: list[tuple[int, int, int, int]] = []
    for elem in root.iter("node"):
        if "EditText" not in (elem.attrib.get("class") or ""):
            continue
        bounds = _parse_bounds(elem.attrib.get("bounds", ""))
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        if right - left < 10 or bottom - top < 10:
            continue
        candidates.append((left, top, right, bottom))
    if not candidates:
        return None
    left, top, right, bottom = min(candidates, key=lambda b: b[1])
    return (left + right) // 2, (top + bottom) // 2


def focus_any_edit_field(
    *,
    xml_text: str | None = None,
    verbose: bool = True,
    settle_sec: float = 0.35,
) -> bool:
    """Тап по первому EditText на экране (не привязан к «Сумма»/TJS)."""
    xml_text = xml_text if xml_text is not None else dump_ui_xml()
    point = find_any_edit_tap(xml_text)
    if point is None:
        if verbose:
            print("    ⌨ UI: EditText не найден")
        return False
    if verbose:
        print(f"    ⌨ UI focus EditText @ {point}")
    tap_raw(*point)
    if settle_sec > 0:
        time.sleep(settle_sec)
    return True


def type_code_smart(
    code: str,
    *,
    gap_sec: float = 0.12,
    verbose: bool = True,
) -> bool:
    """
    Ввод короткого кода (SMS/OTP) в уже открытый экран:
      1) если на экране PIN-подобные кнопки 0-9 — тапаем их;
      2) иначе фокус первого EditText + adb input text (цифры без разделителя,
         фильтр EditText их не режет — не тот случай, что с запятой в сумме).

    Возвращает True, если использовалась in-app клава (см. type_amount_smart).
    """
    xml_text = dump_ui_xml()
    keys = find_key_centers(xml_text)
    if len(keys) >= 10:
        if verbose:
            print(f"    ⌨ код: in-app keypad [{''.join(sorted(keys))}]")
        type_soft_keys(code, gap_sec=gap_sec, verbose=verbose)
        return True

    if verbose:
        print("    ⌨ код: keypad в dump нет → focus первый EditText + input text")
    if not focus_any_edit_field(xml_text=xml_text, verbose=verbose):
        raise RuntimeError(
            "Не найден EditText для кода в UI dump — открой экран SMS-подтверждения"
        )
    if verbose:
        print(f"    ⌨ input text {code!r}")
    type_text_raw(code)
    return False


def focus_amount_field(
    *,
    xml_text: str | None = None,
    verbose: bool = True,
    settle_sec: float = 0.35,
) -> bool:
    """
    Тап по EditText суммы (не по TJS). True если нашли поле.

    xml_text: готовый dump — избежать повторного `uiautomator dump`
    (медленная adb-команда, 1-4с на TECNO).
    """
    xml_text = xml_text if xml_text is not None else dump_ui_xml()
    point = find_amount_edit_tap(xml_text)
    if point is None:
        if verbose:
            print("    ⌨ UI: EditText суммы не найден")
        return False
    if verbose:
        print(f"    ⌨ UI focus сумма @ {point} (лево поля, не TJS)")
    tap_raw(*point)
    if settle_sec > 0:
        time.sleep(settle_sec)
    return True


def type_amount_smart(
    text: str,
    *,
    gap_sec: float = 0.12,
    verbose: bool = True,
) -> bool:
    """
    Сумма Activ:
      1) если на экране PIN-подобные кнопки 0-9 — тапаем их;
      2) иначе фокус EditText «Сумма» + adb input text (Gboard не в dump).

    Возвращает True, если был in-app keypad (PIN-подобные кнопки) —
    тогда после ввода на экране может быть кнопка Done/галочка.
    False — Gboard/EditText: галочки в dump не бывает, tap_soft_done можно
    не гонять (лишний uiautomator dump, 1-4с).
    """
    xml_text = dump_ui_xml()
    keys = find_key_centers(xml_text)
    if len(keys) >= 10:
        if verbose:
            print(f"    ⌨ сумма: in-app keypad [{''.join(sorted(keys))}]")
        type_soft_keys(text, gap_sec=gap_sec, verbose=verbose)
        return True

    if verbose:
        print(
            "    ⌨ сумма: keypad в dump нет (Gboard) → "
            "focus EditText + input text"
        )
    # Один dump уже на руках (использован для find_key_centers) — переиспользуем,
    # не гоняем uiautomator dump второй раз.
    if not focus_amount_field(xml_text=xml_text, verbose=verbose):
        raise RuntimeError(
            "Не найден EditText суммы в UI dump — открой поле «Сумма»"
        )
    if verbose:
        print(f"    ⌨ input text {text!r}")
    type_text_raw(text)
    return False


def tap_soft_done(*, verbose: bool = True, settle_sec: float = 0.3) -> bool:
    """Тап по галочке/Done на UI, если найдена. Иначе False (зови ime_done)."""
    xml_text = dump_ui_xml()
    center = find_action_center(xml_text)
    if center is None:
        if verbose:
            print("    ⌨ softkey Done не найден в UI — будет KEYCODE_ENTER")
        return False
    if verbose:
        print(f"    ⌨ softkey Done @ {center}")
    tap_raw(*center)
    if settle_sec > 0:
        time.sleep(settle_sec)
    return True
