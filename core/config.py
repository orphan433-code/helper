"""Загрузка config.yaml — секции platcore (корень) и bank."""

from __future__ import annotations

from core.paths import ROOT

_BANK_DEFAULTS: dict = {
    "pin": "",
    "pin_screen_markers": ["Activ Bank"],
    "keypad_check_digits": ["1", "5"],
    "focus_delay_sec": 3.0,
    "stage_timeout_sec": 30.0,
    "mirror_focus_sec": 0.4,
    "pin_pre_tap_sec": 0.6,
    "pin_tap_gap_sec": 0.3,
    "pin_tap_same_gap_sec": 0.45,
    "pin_tap_warp_sec": 0.05,
    "pin_first_tap_warp_sec": 0.15,
    "pin_first_tap_hold_sec": 0.08,
    "pin_tap_hold_sec": 0.05,
    "pin_tap_settle_sec": 0.08,
    "pin_first_tap_settle_sec": 0.18,
    "pin_first_tap_twice": True,
    "pin_first_retry_gap_sec": 0.4,
    "pin_prime_tap": True,
    "pin_prime_settle_sec": 0.25,
    "pin_prime_y_offset": -130.0,
    "post_pin_settle_sec": 0.8,
    "pin_screen_found_sec": 0.8,
    "label_payments": "Платежи",
    "label_transfers": "Переводы",
    "label_other_countries": ["Друг стра", "Дру стра", "Друг", "дру", "стра"],
    "nav_timeout_sec": 30.0,
    "nav_pre_tap_sec": 0.35,
    "nav_step_gap_sec": 0.35,
    "nav_post_tap_settle_sec": 1.0,
    "stage2_always_tap_payments": True,
    "payments_tab_min_y_ratio": 0.78,
    "payments_fixed_tap_enabled": True,
    "payments_fixed_x_ratio": 0.36,
    "payments_fixed_y_ratio": 0.93,
    "payments_ocr_timeout_sec": 1.5,
    "nav_mirror_wake_tap": True,
    "nav_first_tap_twice": False,
    "nav_first_tap_retry_gap_sec": 0.35,
    "transfers_max_y_ratio": 0.72,
    "other_tap_icon_offset_y": 45.0,
    "other_tap_on_text": True,
    "other_edge_tap_enabled": False,
    "other_edge_x_ratio": 0.995,
    "other_edge_right_inset": 1.0,
    "other_edge_y_offset": 68.0,
    "bank_handoff_gui_focus_sec": 0.45,
    "bank_handoff_gui_focus_retry": True,
    "bank_handoff_ocr_settle_sec": 0.15,
    "bank_handoff_ready_timeout_sec": 6.0,
    "bank_handoff_ready_poll_sec": 0.22,
    "bank_handoff_ready_refocus_every": 3,
    "mirror_capture_prime": True,
    "mirror_capture_prime_settle_sec": 0.15,
    "carousel_scroll_below_y": 75.0,
    "carousel_scroll_x_offset": 100.0,
    "carousel_scroll_pixels": -8,
    "carousel_scroll_lines": 5,
    "carousel_scroll_method": "pixel",
    "carousel_scroll_pulses": 4,
    "carousel_scroll_pulse_gap": 0.22,
    "carousel_swipe_length": 110.0,
    "carousel_post_scroll_sec": 0.9,
    "carousel_pre_scroll_sec": 0.3,
    "carousel_focus_sec": 0.45,
    "carousel_settle_sec": 0.25,
    "carousel_scroll_max_rounds": 10,
    "label_by_card": ["По номеру карты", "номеру карты"],
    "label_card_number": ["Введите номер карты", "номер карты"],
    "label_holder_name": ["Введите Фамилию и Имя", "Введите фамилию", "фамилию имя"],
    "label_debit_amount": ["Сумма списания", "Сумма"],
    "label_debit_section": "Сумма списания",
    "label_debit_amount_field": "Сумма",
    "label_credit_section": "Сумма зачисления",
    "label_transfer_button": ["Продолжить", "Перевести"],
    "wait_credit_before_continue": True,
    "continue_after_credit_only": True,
    "eur_verify_enabled": True,
    "eur_verify_timeout_sec": 30.0,
    "eur_verify_tolerance": 0.01,
    "eur_verify_poll_sec": 0.5,
    "form_post_transfer_sec": 1.0,
    "post_transfer_enabled": True,
    "review_screen_markers": ["Подтверждение перевода", "Информация о переводе"],
    "label_confirm_transfer_button": ["Подтвердить и перевести", "Подтвердить"],
    "review_timeout_sec": 30.0,
    "review_poll_sec": 0.5,
    "review_post_tap_sec": 1.0,
    "review_eur_verify": True,
    "sms_screen_markers": ["Подтвердите код", "код из смс", "код из SMS"],
    "sms_autofill_markers": ["Источник", "Life", "источ", "source", "lif", "lfe"],
    "sms_code_band_below_y": 35.0,
    "sms_code_band_height": 200.0,
    "sms_band_ocr_scale": 2.0,
    "sms_band_confidence_min": 0.12,
    "sms_screen_confidence_min": 0.2,
    "sms_timeout_sec": 45.0,
    "sms_poll_sec": 0.5,
    "sms_post_tap_sec": 1.5,
    "success_screen_markers": ["Детали перевода"],
    "label_home_button": ["На главную страницу", "На главную"],
    "success_decoy_markers": [
        "Сохранить в частые",
        "Добавить в избранное",
        "Повторить перевод",
        "Избранное",
        "частые",
    ],
    "success_timeout_sec": 60.0,
    "success_poll_sec": 0.5,
    "success_home_settle_sec": 0.1,
    "success_home_stable_polls": 1,
    "success_home_poll_sec": 0.2,
    "home_button_min_below_title_px": 20.0,
    "home_button_min_y_ratio": 0.55,
    "home_post_tap_sec": 1.0,
    "form_field_offset_y": 0.0,
    "form_paste_settle_sec": 0.25,
    "form_keyboard_switch_sec": 0.45,
    "form_key_interval": 0.04,
    "form_ime_chain": True,
    "form_ime_next_sec": 0.25,
    "form_ime_done_sec": 0.35,
    "form_ime_amount_settle_sec": 0.9,
    "form_amount_decimal": ",",
    "form_input_method": "hardware",
    "form_card_input_method": "hardware",
    "form_name_input_method": "hardware",
    "form_amount_input_method": "softkey",
    "keyboard_globe_taps": 0,
    "form_input_retries": 1,
    "bank_pre_focus_sec": 1.5,
    "window_switch_settle_sec": 0.0,
    "skip_eur_refresh_if_present": True,
    "bank_handoff_fast": True,
    "bank_handoff_focus_sec": 0.35,
    "bank_handoff_nav_settle_sec": 0.35,
    "bank_handoff_transfers_poll_sec": 0.18,
    "bank_handoff_step_gap_sec": 0.15,
    "tap_after_ocr_immediate": True,
    "tap_after_ocr_pre_sec": 0.0,
    "form_field_offset_x": 0.0,
    "form_pre_tap_sec": 0.35,
    "form_after_type_sec": 0.3,
    "form_step_gap_sec": 0.15,
    "form_timeout_sec": 30.0,
    "form_burst_fill": True,
    "form_between_fields_refocus": False,
    "form_screen_settle_sec": 0.35,
    "form_followup_pre_tap_sec": 0.06,
    "form_field_poll_sec": 0.22,
    "transfer_account": "",
    "transfer_holder": "",
    "transfer_amount_tjs": None,
    "transfer_amount_eur": None,
    "debug_mode": False,
    "debug_screen_path": "debug_screen.png",
    "device_mode": "android",
    "adb_serial": None,
    "tap_jitter_px": 4,
    "bank_humanize": True,
    "bank_click_pause_min_sec": 0.06,
    "bank_click_pause_max_sec": 0.18,
    "bank_timing_jitter_pct": 0.12,
    "form_key_interval_jitter_pct": 0.15,
    "languages": ["ru-RU", "en-US", "zh-Hans"],
    "confidence_min": 0.35,
    "click_timeout_sec": 30.0,
    "click_retry_count": 3,
    "fast_mode": False,
    "timing_profile": "safe",
}

# Ключи, которые профили НЕ перетирают (окна, карусель, wake/focus устройства).
_TIMING_PROFILE_SKIP_KEYS: frozenset[str] = frozenset({
    "bank_pre_focus_sec",
    "window_switch_settle_sec",
    "bank_handoff_focus_sec",
    "bank_handoff_nav_settle_sec",
    "bank_handoff_transfers_poll_sec",
    "bank_handoff_step_gap_sec",
    "bank_handoff_gui_focus_sec",
    "mirror_focus_sec",
    "focus_delay_sec",
    "post_pin_settle_sec",
    "pin_screen_found_sec",
    "form_screen_settle_sec",
    "nav_step_gap_sec",
    "nav_post_tap_settle_sec",
    "transfers_max_y_ratio",
    "nav_pre_tap_sec",
    "carousel_scroll_pulses",
    "carousel_scroll_pulse_gap",
    "carousel_post_scroll_sec",
    "carousel_pre_scroll_sec",
    "carousel_focus_sec",
    "carousel_settle_sec",
    "carousel_scroll_max_rounds",
})

# Устаревшее имя — то же множество.
_FAST_MODE_SKIP_KEYS = _TIMING_PROFILE_SKIP_KEYS

# balanced: быстрее safe, с запасом на UI банка.
_BANK_BALANCED_OVERRIDES: dict = {
    "pin_pre_tap_sec": 0.45,
    "pin_tap_gap_sec": 0.22,
    "pin_tap_same_gap_sec": 0.32,
    "pin_first_retry_gap_sec": 0.28,
    "pin_prime_settle_sec": 0.15,
    "pin_first_tap_settle_sec": 0.12,
    "post_pin_settle_sec": 0.55,
    "pin_screen_found_sec": 0.45,
    "form_pre_tap_sec": 0.28,
    "form_keyboard_switch_sec": 0.32,
    "form_after_type_sec": 0.28,
    "form_step_gap_sec": 0.12,
    "form_paste_settle_sec": 0.2,
    "form_key_interval": 0.045,
    "form_screen_settle_sec": 0.3,
    "form_followup_pre_tap_sec": 0.0,
    "form_field_poll_sec": 0.18,
    "form_post_transfer_sec": 0.65,
    "review_post_tap_sec": 0.7,
    "sms_post_tap_sec": 1.0,
    "home_post_tap_sec": 0.75,
    "success_home_settle_sec": 0.35,
    "success_home_poll_sec": 0.22,
    "eur_verify_poll_sec": 0.35,
    "review_poll_sec": 0.35,
    "sms_poll_sec": 0.35,
    "success_poll_sec": 0.35,
    "debug_mode": False,
}

# fast: максимальная скорость кликов/ввода (рискованнее для UI банка).
_BANK_FAST_OVERRIDES: dict = {
    "focus_delay_sec": 0.0,
    "pin_pre_tap_sec": 0.2,
    "pin_tap_gap_sec": 0.12,
    "pin_tap_same_gap_sec": 0.18,
    "pin_first_retry_gap_sec": 0.15,
    "pin_prime_settle_sec": 0.06,
    "pin_first_tap_settle_sec": 0.08,
    "post_pin_settle_sec": 0.2,
    "pin_screen_found_sec": 0.15,
    "form_pre_tap_sec": 0.06,
    "form_keyboard_switch_sec": 0.06,
    "form_after_type_sec": 0.03,
    "form_step_gap_sec": 0.03,
    "form_paste_settle_sec": 0.08,
    "form_key_interval": 0.018,
    "form_post_transfer_sec": 0.12,
    "review_post_tap_sec": 0.15,
    "sms_post_tap_sec": 0.2,
    "home_post_tap_sec": 0.15,
    "eur_verify_poll_sec": 0.15,
    "review_poll_sec": 0.15,
    "sms_poll_sec": 0.15,
    "success_poll_sec": 0.15,
    "debug_mode": False,
}

_TIMING_PROFILE_OVERRIDES: dict[str, dict] = {
    "safe": {},
    "balanced": _BANK_BALANCED_OVERRIDES,
    "fast": _BANK_FAST_OVERRIDES,
}


def resolve_timing_profile(user: dict) -> str:
    """safe | balanced | fast. legacy: fast_mode=true → fast."""
    raw = str(user.get("timing_profile") or "").strip().lower()
    if raw in _TIMING_PROFILE_OVERRIDES:
        return raw
    if user.get("fast_mode"):
        return "fast"
    return "safe"


def bank_settings(cfg: dict | None = None) -> dict:
    """Все настройки BANK: PIN, OCR, adb, тайминги тапов."""
    cfg = cfg or load_config()
    legacy_ocr = cfg.get("ocr") or {}
    user = dict(cfg.get("bank") or {})
    merged = {**_BANK_DEFAULTS, **legacy_ocr, **user}

    profile = resolve_timing_profile(user)
    overrides = _TIMING_PROFILE_OVERRIDES[profile]
    if overrides:
        for key, value in overrides.items():
            if key not in _TIMING_PROFILE_SKIP_KEYS:
                merged[key] = value
    merged["timing_profile"] = profile
    merged["fast_mode"] = profile == "fast"

    # Явные значения из config.yaml для «жёстких» ключей (окна, карусель).
    for key, value in user.items():
        if key in _TIMING_PROFILE_SKIP_KEYS or key not in overrides:
            merged[key] = value
    return merged


def load_config() -> dict:
    import yaml

    path = ROOT / "config.yaml"
    if not path.exists():
        path = ROOT / "config.example.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def completion_settings(cfg: dict | None = None) -> dict:
    """Секция completion — фаза 2 (скрины → Money sent)."""
    if cfg is None:
        cfg = load_config()
    defaults = {
        "enabled": True,
        "save_proofs_on_success": False,
        "capture_mirror_on_enter": False,
        "require_success_status": False,
        "proofs_dir": "~/Downloads",
        "videos_dir": "~/Downloads",
        "video_min_usdt": 225.0,
        "watch_grace_sec": 5.0,
        "batch_file": "runtime/completion_batch.json",
        "dispute_topic": "Хук не дошел",
        "dispute_message": (
            "Отменяем, не ушло. Если перевод не прошёл он пропадает из истории"
        ),
        "fake_dispute": False,
    }
    user = cfg.get("completion") or {}
    merged = dict(defaults)
    merged.update(user)
    return merged


def save_config(cfg: dict) -> None:
    import yaml

    path = ROOT / "config.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def ocr_settings(cfg: dict | None = None) -> dict:
    """OCR — читается из секции bank (ocr: в корне — устарело)."""
    return bank_settings(cfg)


def is_android_mode(cfg: dict | None = None) -> bool:
    """Всегда Android (iPhone-путь удалён)."""
    _ = cfg
    return True


def capture_region(cfg: dict | None = None) -> tuple[int, int, int, int] | None:
    """Область OCR: полный экран телефона через adb."""
    from device.adb import get_display_size, require_device

    _ = cfg
    require_device()
    w, h = get_display_size()
    return 0, 0, w, h


def capture_region_or_raise(cfg: dict | None = None) -> tuple[int, int, int, int]:
    region = capture_region(cfg)
    if region is not None:
        return region
    raise RuntimeError("adb не видит телефон — USB и «Отладка по USB»")
