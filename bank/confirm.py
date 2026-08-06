"""Bank flow — этап 4–5: SMS-код (autofill) и «На главную страницу»."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from PIL import Image

from bank.form import BankFormError, BankPostPaymentError
from bank.screen import find_labels, scan_screen
from core.config import bank_settings, capture_region_or_raise, completion_settings
from device.clicker import tap_after_ocr
from device.ocr import OcrHit, run_ocr
from device.screenshot import get_retina_scale, take_screenshot

_SMS_CODE_RE = re.compile(r"\b(\d{4})\b")
_SMS_CODE_FRAGMENT_RE = re.compile(r"^\d{3,4}$")
_TIMER_RE = re.compile(r"^\d{2}:\d{2}$")


@dataclass
class SmsArm:
    """Метка свежести SMS: снимок шторки в момент тапа «Подтвердить»."""

    since_wall_ms: float
    baseline_keys: set[str] = field(default_factory=set)


def _labels(raw: str | list[str]) -> list[str]:
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def _confirm_cfg() -> dict:
    bank = bank_settings()
    return {
        "post_transfer_enabled": bool(bank.get("post_transfer_enabled", True)),
        "review_screen_markers": _labels(
            bank.get("review_screen_markers")
            or ["Подтверждение", "Подтверждение перевода", "Информация о переводе"]
        ),
        "confirm_transfer_button": _labels(
            bank.get("label_confirm_transfer_button")
            or ["Перевести", "Подтвердить и перевести", "Подтвердить"]
        ),
        "review_timeout_sec": float(bank.get("review_timeout_sec", 30)),
        "review_poll_sec": float(bank.get("review_poll_sec", 0.5)),
        "review_post_tap_sec": float(bank.get("review_post_tap_sec", 1.0)),
        "review_eur_verify": bool(bank.get("review_eur_verify", True)),
        "sms_screen_markers": _labels(
            bank.get("sms_screen_markers")
            or ["Подтвердите код", "код из смс", "код из SMS"]
        ),
        "sms_autofill_markers": _labels(
            bank.get("sms_autofill_markers")
            or ["Источник", "Life", "источ", "source", "lif", "lfe"]
        ),
        "sms_code_band_below_y": float(bank.get("sms_code_band_below_y", 35)),
        "sms_code_band_height": float(bank.get("sms_code_band_height", 200)),
        "sms_band_ocr_scale": float(bank.get("sms_band_ocr_scale", 2.0)),
        "sms_band_confidence_min": float(bank.get("sms_band_confidence_min", 0.12)),
        "sms_screen_confidence_min": float(bank.get("sms_screen_confidence_min", 0.2)),
        "sms_timeout_sec": float(bank.get("sms_timeout_sec", 45)),
        "sms_poll_sec": float(bank.get("sms_poll_sec", 0.5)),
        "sms_post_tap_sec": float(bank.get("sms_post_tap_sec", 1.5)),
        # notification — читать код через `adb shell dumpsys notification`
        # (Android, надёжно). autofill — старый OCR-пузырь (легаси с iOS,
        # на Android такого пузыря нет — не работает).
        "sms_input_method": str(bank.get("sms_input_method", "notification")),
        "sms_notify_pkg_filter": (
            str(bank.get("sms_notify_pkg_filter"))
            if bank.get("sms_notify_pkg_filter") is not None
            else "polyphone"
        ),
        "sms_notify_poll_sec": float(bank.get("sms_notify_poll_sec", 0.6)),
        "success_screen_markers": _labels(
            bank.get("success_screen_markers") or ["Детали перевода"]
        ),
        "home_button": _labels(
            bank.get("label_home_button") or ["На главную страницу", "На главную"]
        ),
        # Иконки выше «На главную» — не путать с красной кнопкой внизу.
        "success_decoy_markers": _labels(
            bank.get("success_decoy_markers")
            or [
                "Сохранить в частые",
                "Добавить в избранное",
                "Повторить перевод",
                "Избранное",
                "частые",
            ]
        ),
        "success_timeout_sec": float(bank.get("success_timeout_sec", 60)),
        "success_poll_sec": float(bank.get("success_poll_sec", 0.5)),
        "success_home_settle_sec": float(bank.get("success_home_settle_sec", 0.1)),
        "success_home_stable_polls": int(bank.get("success_home_stable_polls", 1)),
        "success_home_poll_sec": float(
            bank.get("success_home_poll_sec", bank.get("success_poll_sec", 0.5))
        ),
        "home_button_min_below_title_px": float(
            bank.get("home_button_min_below_title_px", 20)
        ),
        # Настоящая «На главную» — в нижней половине экрана.
        "home_button_min_y_ratio": float(bank.get("home_button_min_y_ratio", 0.55)),
        "home_post_tap_sec": float(bank.get("home_post_tap_sec", 1.0)),
        "mirror_focus_sec": float(bank.get("mirror_focus_sec", 0.45)),
        "form_pre_tap_sec": float(bank.get("form_pre_tap_sec", 0.35)),
    }


def is_transfer_review_screen(hits: list[OcrHit], cfg: dict) -> bool:
    return find_labels(hits, cfg["review_screen_markers"], partial=True) is not None


def find_confirm_transfer_button(hits: list[OcrHit], cfg: dict) -> OcrHit:
    hit = find_labels(hits, cfg["confirm_transfer_button"], partial=True)
    if hit is not None:
        return hit
    raise BankFormError(f"OCR не видит кнопку {cfg['confirm_transfer_button']!r}")


def read_review_credit_eur(hits: list[OcrHit]) -> float | None:
    """«Сумма зачисления» на экране «Подтверждение перевода» → 29,89 EUR."""
    from bank.form import _parse_eur_value

    section = find_labels(hits, ["Сумма зачисления"], partial=True)
    if section is None:
        return None

    for hit in hits:
        if abs(hit.y - section.y) > 24:
            continue
        if hit.x < section.x - 30:
            continue
        hay = hit.text.strip().lower()
        if hay in ("сумма зачисления", "сумма"):
            continue
        value = _parse_eur_value(hit.text)
        if value is not None:
            return value
    return None


def run_stage3c_confirm_review(
    *,
    region: tuple[int, int, int, int] | None = None,
    expected_eur: float | None = None,
    verbose: bool = True,
) -> SmsArm | None:
    """Этап 3c: «Подтверждение перевода» → «Подтвердить и перевести».

    В момент тапа подтверждения снимает SmsArm (метка + baseline шторки),
    чтобы этап 4 не подхватил старый OTP.
    """
    from bank.form import _reconcile_eur_ocr
    from notify.sms import snapshot_notification_keys

    cfg = _confirm_cfg()
    capture = region if region is not None else capture_region_or_raise()
    if capture is None:
        raise BankFormError("capture_region не задан")

    if verbose:
        print("[INFO] Этап 3c: ждём «Подтверждение перевода»…")

    deadline = time.monotonic() + cfg["review_timeout_sec"]
    tolerance = float(bank_settings().get("eur_verify_tolerance", 0.01))

    while time.monotonic() < deadline:
        hits = scan_screen(capture)
        if not is_transfer_review_screen(hits, cfg):
            # Если маркеры review вдруг не совпали (другая версия банка/OCR),
            # но экран уже реально ушёл на SMS/успех — не падаем, а просто
            # пропускаем этот шаг вместо жёсткого таймаута на 30 с.
            if is_sms_confirm_screen(hits, cfg) or is_transfer_success_screen(hits, cfg):
                if verbose:
                    print(
                        "[INFO] Этап 3c: экран review не распознан по "
                        "маркерам, но уже видно SMS/успех — пропускаем тап"
                    )
                # Тапа не было — baseline пустой (иначе свежий OTP уже в шторке
                # попал бы в «старые»). Метка — чуть раньше, с запасом.
                return SmsArm(
                    since_wall_ms=time.time() * 1000 - 20_000,
                    baseline_keys=set(),
                )
            time.sleep(cfg["review_poll_sec"])
            continue

        if expected_eur and cfg["review_eur_verify"]:
            raw = read_review_credit_eur(hits)
            if raw is not None:
                actual = _reconcile_eur_ocr(raw, expected_eur, tolerance)
                if abs(actual - expected_eur) > tolerance:
                    raise BankFormError(
                        f"На экране подтверждения {actual:g} EUR "
                        f"≠ ожидалось {expected_eur:g} EUR"
                    )
                if verbose:
                    note = f" (OCR {raw:g} → {actual:g})" if raw != actual else ""
                    print(f"[OK] EUR на экране подтверждения: {actual:g}{note}")

        try:
            btn = find_confirm_transfer_button(hits, cfg)
        except BankFormError:
            time.sleep(cfg["review_poll_sec"])
            continue

        if verbose:
            print(f"[INFO] Тап «{btn.text}» @ ({btn.x:.0f}, {btn.y:.0f})")

        # Снимок шторки ДО тапа: всё, что уже висело — старое.
        arm = SmsArm(
            since_wall_ms=time.time() * 1000,
            baseline_keys=snapshot_notification_keys(
                pkg_filter=cfg["sms_notify_pkg_filter"] or None
            ),
        )
        if verbose:
            print(
                f"[INFO] SMS-arm: baseline={len(arm.baseline_keys)} "
                "уведомлений (старые OTP не берём)"
            )

        tap_after_ocr(
            btn.x,
            btn.y,
            verbose=verbose,
            label=btn.text,
        )

        gap = cfg["review_post_tap_sec"]
        if gap > 0:
            time.sleep(gap)

        if verbose:
            print("[OK] Этап 3c: «Подтвердить и перевести» — ждём SMS")
        return arm

    raise BankFormError(
        f"Экран «Подтверждение перевода» не появился за {cfg['review_timeout_sec']:.0f} с"
    )


def is_sms_confirm_screen(hits: list[OcrHit], cfg: dict) -> bool:
    return find_labels(hits, cfg["sms_screen_markers"], partial=True) is not None


def is_transfer_success_screen(hits: list[OcrHit], cfg: dict) -> bool:
    return find_labels(hits, cfg["success_screen_markers"], partial=True) is not None


def _is_sms_code_fragment(text: str) -> bool:
    raw = text.strip()
    if not raw or _TIMER_RE.match(raw):
        return False
    if re.search(r"\+\d", raw) or re.search(r"\(\d{2}\)", raw):
        return False
    if not _SMS_CODE_FRAGMENT_RE.match(raw):
        return False
    return not raw.startswith("00")


def _is_sms_code_text(text: str) -> bool:
    raw = text.strip()
    if not raw or _TIMER_RE.match(raw):
        return False
    if re.search(r"\+\d", raw):
        return False
    if re.search(r"\(\d{2}\)", raw):
        return False
    m = _SMS_CODE_RE.search(raw)
    if not m:
        return False
    code = m.group(1)
    return not code.startswith("00")


def _sms_code_band_rect(
    hits: list[OcrHit],
    cfg: dict,
) -> tuple[float, float] | None:
    anchor = find_labels(hits, cfg["sms_screen_markers"], partial=True)
    if anchor is None:
        return None

    y_min = anchor.y + cfg["sms_code_band_below_y"]
    y_max = anchor.y + cfg["sms_code_band_height"]
    resend = find_labels(hits, ["Запросить", "повторно", "повтор"], partial=True)
    if resend is not None:
        y_max = min(y_max, resend.y - 12)
    if y_max - y_min < 20:
        return None
    return y_min, y_max


def _hits_in_sms_code_band(hits: list[OcrHit], cfg: dict) -> list[OcrHit]:
    """Область между заголовком SMS и кнопкой «Запросить повторно»."""
    rect = _sms_code_band_rect(hits, cfg)
    if rect is None:
        return hits
    y_min, y_max = rect
    return [h for h in hits if y_min <= h.y <= y_max]


def scan_sms_autofill_band(
    capture: tuple[int, int, int, int],
    hits: list[OcrHit],
    cfg: dict,
) -> list[OcrHit]:
    """Повторный OCR только полосы с пузырём — крупнее и с ниже порогом."""
    rect = _sms_code_band_rect(hits, cfg)
    if rect is None:
        return []

    y_min, y_max = rect
    left, top, rw, _rh = capture
    band_h = int(y_max - y_min)
    if band_h < 20:
        return []

    sub_region = (left, int(y_min), rw, band_h)
    image = take_screenshot(region=capture)
    scale = get_retina_scale(image, region=capture)
    rel_y0 = max(0, int((y_min - top) * scale))
    rel_y1 = min(image.height, int((y_max - top) * scale))
    if rel_y1 - rel_y0 < 10:
        return []

    crop = image.crop((0, rel_y0, image.width, rel_y1))
    ocr_scale = cfg["sms_band_ocr_scale"]
    if ocr_scale > 1.0:
        crop = crop.resize(
            (int(crop.width * ocr_scale), int(crop.height * ocr_scale)),
            Image.Resampling.LANCZOS,
        )

    return run_ocr(
        crop,
        region=sub_region,
        confidence_min=cfg["sms_band_confidence_min"],
    )


def scan_sms_screen(
    capture: tuple[int, int, int, int],
    cfg: dict,
) -> list[OcrHit]:
    """OCR SMS-экрана с пониженным порогом — пузырь часто conf 0.4–0.5."""
    image = take_screenshot(region=capture)
    return run_ocr(
        image,
        region=capture,
        confidence_min=cfg["sms_screen_confidence_min"],
    )


def _is_bubble_digit_hit(hit: OcrHit, hits: list[OcrHit]) -> bool:
    raw = hit.text.strip()
    if not (_is_sms_code_text(raw) or _is_sms_code_fragment(raw)):
        return False
    if re.search(r"запрос|повтор", raw, re.I):
        return False
    resend = find_labels(hits, ["Запросить", "повторно", "повтор"], partial=True)
    if resend is not None and hit.y >= resend.y - 16:
        return False
    return True


def _pick_bubble_digit_hit(
    band: list[OcrHit],
    hits: list[OcrHit],
) -> OcrHit | None:
    """Любой SMS-код (3–4 цифры) в пузыре, не таймер «00:54» на кнопке."""
    candidates = [h for h in band if _is_bubble_digit_hit(h, hits)]
    if not candidates:
        return None
    return min(candidates, key=lambda h: (h.y, h.x))


def find_sms_autofill_hit(
    hits: list[OcrHit],
    cfg: dict,
) -> OcrHit | None:
    """
    Пузырь iOS autofill: тап по «Источник» / «Life» (код не важен).
    Запасной вариант — любые 3–4 цифры кода в полосе пузыря.
    """
    band = _hits_in_sms_code_band(hits, cfg)

    for word in cfg["sms_autofill_markers"]:
        hit = find_labels(band, [word], partial=True)
        if hit is not None:
            return hit

    for word in cfg["sms_autofill_markers"]:
        hit = find_labels(hits, [word], partial=True)
        if hit is not None:
            return hit

    return _pick_bubble_digit_hit(band, hits)


def _tap_sms_autofill(
    x: float,
    y: float,
    *,
    label: str,
    cfg: dict,
    verbose: bool,
) -> None:
    tap_after_ocr(x, y, verbose=verbose, label=label)
    gap = cfg["sms_post_tap_sec"]
    if gap > 0:
        time.sleep(gap)


def _home_label_hits(hits: list[OcrHit], labels: list[str]) -> list[OcrHit]:
    """Все OCR-хиты, подходящие под подписи «На главную» (не только первый)."""
    needles = [lab.strip().lower() for lab in labels if lab and str(lab).strip()]
    found: list[OcrHit] = []
    for hit in hits:
        hay = hit.text.lower()
        if any(n in hay for n in needles):
            found.append(hit)
    return found


def find_home_button(hits: list[OcrHit], cfg: dict) -> OcrHit:
    candidates = _home_label_hits(hits, cfg["home_button"])
    if not candidates:
        raise BankFormError(f"OCR не видит кнопку {cfg['home_button']!r}")
    # Если OCR видит несколько совпадений — берём самое нижнее (красная кнопка).
    hit = max(candidates, key=lambda h: h.y)

    from device.adb import get_display_size

    _w, screen_h = get_display_size()
    min_ratio = float(cfg.get("home_button_min_y_ratio", 0.68))
    min_y = screen_h * min_ratio
    if hit.y < min_y:
        raise BankFormError(
            f"Кнопка «{hit.text}» слишком высоко "
            f"(y={hit.y:.0f} < {min_y:.0f}) — экран ещё анимируется "
            f"или это зона «Избранное»"
        )

    title = find_labels(hits, cfg["success_screen_markers"], partial=True)
    min_below = float(cfg.get("home_button_min_below_title_px", 20))
    if title is not None and hit.y < title.y + min_below:
        raise BankFormError(
            f"Кнопка «{hit.text}» выше заголовка успеха — экран ещё грузится"
        )
    # «Сохранить в частые» / «Добавить в избранное» — выше настоящей кнопки.
    decoy = find_labels(hits, cfg.get("success_decoy_markers") or [], partial=True)
    if decoy is not None and hit.y < decoy.y + min_below:
        raise BankFormError(
            f"Кнопка «{hit.text}» на уровне «{decoy.text}» — похоже на промах"
        )
    return hit


def _try_find_home_button(hits: list[OcrHit], cfg: dict) -> OcrHit | None:
    try:
        return find_home_button(hits, cfg)
    except BankFormError:
        return None


def run_stage4_sms_autofill(
    *,
    region: tuple[int, int, int, int] | None = None,
    verbose: bool = True,
) -> None:
    """Этап 4: ждём SMS-экран → тап «Источник: Life …» для autofill."""
    cfg = _confirm_cfg()
    capture = region if region is not None else capture_region_or_raise()
    if capture is None:
        raise BankFormError("capture_region не задан")

    if verbose:
        print("[INFO] Этап 4: ждём экран SMS-подтверждения…")

    deadline = time.monotonic() + cfg["sms_timeout_sec"]
    last_band_log = 0.0

    while time.monotonic() < deadline:
        hits = scan_sms_screen(capture, cfg)
        if not is_sms_confirm_screen(hits, cfg):
            time.sleep(cfg["sms_poll_sec"])
            continue

        autofill = find_sms_autofill_hit(hits, cfg)
        if autofill is None:
            band_hits = scan_sms_autofill_band(capture, hits, cfg)
            if band_hits:
                autofill = find_sms_autofill_hit(hits + band_hits, cfg)

        if autofill is not None:
            code_match = _SMS_CODE_RE.search(autofill.text)
            if code_match is not None:
                code_hint = code_match.group(1)
            else:
                frag = _SMS_CODE_FRAGMENT_RE.match(autofill.text.strip())
                code_hint = frag.group(0) if frag else autofill.text
            if verbose:
                print(
                    f"[INFO] Тап по «{autofill.text}» @ "
                    f"({autofill.x:.0f}, {autofill.y:.0f})"
                    + (f" (код {code_hint})" if code_hint != autofill.text else "")
                )
            _tap_sms_autofill(
                autofill.x,
                autofill.y,
                label=autofill.text,
                cfg=cfg,
                verbose=verbose,
            )
            if verbose:
                print("[OK] Этап 4: SMS-код вставлен через autofill")
            return

        now = time.monotonic()
        if verbose and now - last_band_log >= 1.5:
            band = _hits_in_sms_code_band(hits, cfg)
            preview = ", ".join(h.text for h in band[:10]) or "пусто"
            print(f"[INFO] SMS-экран, ищем пузырь… OCR в полосе: {preview}")
            last_band_log = now

        time.sleep(cfg["sms_poll_sec"])

    raise BankFormError(
        f"SMS-подтверждение не завершено за {cfg['sms_timeout_sec']:.0f} с"
    )


def run_stage4_sms_notification(
    *,
    region: tuple[int, int, int, int] | None = None,
    verbose: bool = True,
    sms_arm: SmsArm | None = None,
) -> None:
    """
    Этап 4 (Android): ждём SMS-экран → код из `dumpsys notification` →
    вводим в поле. «Далее»/Enter не жмём — банк сам меняет экран на успех.

    sms_arm — снимок с тапа «Подтвердить» (предпочтительно); иначе метка
    ставится здесь (хуже: старые OTP из шторки могут проскочить).
    """
    from device.softkey import type_code_smart
    from notify.sms import snapshot_notification_keys, wait_for_sms_code

    cfg = _confirm_cfg()
    if sms_arm is not None:
        entry_wall_ms = sms_arm.since_wall_ms
        baseline_keys = set(sms_arm.baseline_keys)
    else:
        entry_wall_ms = time.time() * 1000
        baseline_keys = snapshot_notification_keys(
            pkg_filter=cfg["sms_notify_pkg_filter"] or None
        )

    capture = region if region is not None else capture_region_or_raise()
    if capture is None:
        raise BankFormError("capture_region не задан")

    if verbose:
        print("[INFO] Этап 4: ждём экран SMS-подтверждения…")

    deadline = time.monotonic() + cfg["sms_timeout_sec"]
    while time.monotonic() < deadline:
        hits = scan_sms_screen(capture, cfg)
        if is_sms_confirm_screen(hits, cfg):
            break
        if is_transfer_success_screen(hits, cfg):
            if verbose:
                print("[INFO] Этап 4: SMS не потребовался — уже экран успеха")
            return
        time.sleep(cfg["sms_poll_sec"])
    else:
        raise BankFormError(
            f"Экран SMS-подтверждения не появился за {cfg['sms_timeout_sec']:.0f} с"
        )

    remaining = max(5.0, deadline - time.monotonic())
    code = wait_for_sms_code(
        timeout_sec=remaining,
        poll_sec=cfg["sms_notify_poll_sec"],
        pkg_filter=cfg["sms_notify_pkg_filter"] or None,
        since_wall_ms=entry_wall_ms,
        baseline_keys=baseline_keys,
        verbose=verbose,
    )

    type_code_smart(code, verbose=verbose)
    if verbose:
        print("[OK] Этап 4: код введён — ждём экран успеха (без тапа «Далее»)")


def run_stage5_return_home(
    *,
    region: tuple[int, int, int, int] | None = None,
    verbose: bool = True,
) -> None:
    """Этап 5: как только видна «На главную» внизу — скрин (если нужен) и тап."""
    cfg = _confirm_cfg()
    capture = region if region is not None else capture_region_or_raise()
    if capture is None:
        raise BankFormError("capture_region не задан")

    poll = cfg["success_home_poll_sec"]
    settle = cfg["success_home_settle_sec"]
    stable_need = max(1, cfg["success_home_stable_polls"])

    if verbose:
        print("[INFO] Этап 5: ждём «На главную» → скрин → тап…")

    deadline = time.monotonic() + cfg["success_timeout_sec"]
    stable_count = 0
    btn: OcrHit | None = None

    while time.monotonic() < deadline:
        hits = scan_screen(capture)
        candidate = _try_find_home_button(hits, cfg)
        if candidate is None:
            stable_count = 0
            time.sleep(poll)
            continue

        btn = candidate
        stable_count += 1
        if stable_count < stable_need:
            if verbose:
                print(
                    f"    … «{btn.text}» ({stable_count}/{stable_need}), "
                    f"@ ({btn.x:.0f}, {btn.y:.0f})"
                )
            time.sleep(poll)
            continue
        break
    else:
        raise BankPostPaymentError(
            f"Кнопка «На главную» не появилась за {cfg['success_timeout_sec']:.0f} с "
            "(оплата уже прошла — не повторяй перевод)"
        )

    assert btn is not None
    if settle > 0:
        time.sleep(settle)

    comp = completion_settings()
    if comp.get("save_proofs_on_success"):
        try:
            from completion.proof import save_success_proof_before_home

            save_success_proof_before_home()
            hits = scan_screen(capture)
            refreshed = _try_find_home_button(hits, cfg)
            if refreshed is not None:
                btn = refreshed
        except Exception as exc:
            if verbose:
                print(f"[WARN] Сохранение чека: {exc}")

    if verbose:
        print(f"[INFO] Успех: тап «{btn.text}» @ ({btn.x:.0f}, {btn.y:.0f})")

    tap_after_ocr(
        btn.x,
        btn.y,
        verbose=verbose,
        label=btn.text,
        refocus=False,
        pre_tap_sec=0.0,
    )

    gap = cfg["home_post_tap_sec"]
    if gap > 0:
        time.sleep(gap)

    if verbose:
        print("[OK] Этап 5: на главной — готово к следующему кругу")


def run_post_transfer_steps(
    *,
    region: tuple[int, int, int, int] | None = None,
    expected_eur: float | None = None,
    verbose: bool = True,
) -> None:
    """Этапы 3c–5 после 2-го «Перевести» на форме."""
    cfg = _confirm_cfg()
    if not cfg["post_transfer_enabled"]:
        if verbose:
            print("[INFO] Этапы 3c–5 пропущены (post_transfer_enabled: false)")
        return

    sms_arm = run_stage3c_confirm_review(
        region=region,
        expected_eur=expected_eur,
        verbose=verbose,
    )
    if cfg["sms_input_method"] == "autofill":
        run_stage4_sms_autofill(region=region, verbose=verbose)
    else:
        run_stage4_sms_notification(
            region=region, verbose=verbose, sms_arm=sms_arm
        )
    run_stage5_return_home(region=region, verbose=verbose)
