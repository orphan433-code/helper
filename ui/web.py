#!/usr/bin/env python3
"""tzk — нативное окно (pywebview + WKWebView на macOS)."""

from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import sys
import threading
import traceback
from typing import Any, Callable, Literal

from core.paths import ROOT

from completion.registry import proofs_dir, videos_dir
from core.logkit import make_event, set_ui_sink
from core.config import bank_settings, load_config
from core.decline_bins import DECLINE_BIN_PREFIXES, clamp_decline_limit
from core.redirect_bins import REDIRECT_BIN_PREFIXES
from core.redirect_rules import REDIRECT_MAX_REMAINING_HOURS
from core.ensure_configs import ensure_local_configs
from ui.hooks import (
    clear_job_window_hooks,
    enter_background,
    enter_foreground,
    is_bank_phase,
    is_completion_phase,
    reset_window_session,
    set_automation_phase,
    set_gui_mode,
    set_job_window_hooks,
)
from ui.progress import (
    clear_completion_progress_handler,
    clear_pipeline_progress_handler,
    set_completion_progress_handler,
    set_pipeline_progress_handler,
)
from core.pipeline_bins import PIPELINE_BIN_PREFIXES
from core.accept_names import ACCEPT_NAMES_DEFAULT_MAX
from ui.settings import (
    apply_gui_settings,
    apply_pipeline_bin_filters,
    apply_redirect_filters,
    apply_redirect_bin_filters,
    apply_decline_bin_filters,
    decline_bin_settings,
    redirect_bin_settings,
    decline_tbc_enabled,
    decline_max_per_run,
    pipeline_bin_settings,
    decline_amount_settings,
    redirect_amount_settings,
    apply_redirect_amounts,
    redirect_filter_settings,
)
from ui.job_control import begin_job, request_stop
from pipeline.runner import run_login, run_pipeline
from core.self_update import apply_update, read_version, update_status
from ui.prompts import set_confirm_handler, set_recovery_handler

JobMode = Literal["", "pipeline", "login", "decline", "redirect", "accept_names"]
WEB_UI = ROOT / "web_ui" / "dist" / "index.html"
WEB_UI_LEGACY = ROOT / "web_ui" / "index.legacy.html"
# Decline внутри репо (раньше лежал рядом: ../platcore-decline)
DECLINE_DIR = ROOT / "platcore-decline"
DECLINE_SCRIPT = DECLINE_DIR / "decline_by_bank_api.py"
# setup.sh кладёт venv в TJSBOT/.venv; старый layout — соседний parent/.venv
_PYTHON_CANDIDATES = (
    ROOT / ".venv" / "bin" / "python",
    ROOT / ".venv" / "bin" / "python3",
    ROOT.parent / ".venv" / "bin" / "python3",
    ROOT.parent / ".venv" / "bin" / "python",
)
PYTHON = next((p for p in _PYTHON_CANDIDATES if p.is_file()), _PYTHON_CANDIDATES[0])


def _adb_status_text() -> tuple[str, bool]:
    """(текст для UI, устройство подключено)."""
    try:
        from device.adb import (
            adb_bin,
            get_display_size,
            invalidate_serial_cache,
            pick_serial,
            require_device,
        )

        invalidate_serial_cache()
        serial = require_device()
        w, h = get_display_size()
        label = serial or pick_serial() or "device"
        kind = "wifi" if (serial and (":" in serial or "_adb-tls" in serial)) else "usb"
        return f"{label} ({kind}) — {w}×{h} [{adb_bin()}]", True
    except Exception as exc:
        return f"не подключён ({exc})", False



class LogRedirector:
    """Чужой print() во время job → только в консоль. В UI-журнал не льём."""

    def __init__(self, push_event=None) -> None:
        self._push_event = push_event

    def write(self, text: str) -> None:
        if not text:
            return
        try:
            sys.__stdout__.write(text)
            sys.__stdout__.flush()
        except Exception:
            pass

    def flush(self) -> None:
        try:
            sys.__stdout__.flush()
        except Exception:
            pass


class TzkApi:
    """Мост Python ↔ JavaScript (pywebview js_api)."""

    def __init__(self) -> None:
        self._window: Any = None
        self._log_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=2000)
        set_ui_sink(self._push_log_event)
        self._worker: threading.Thread | None = None
        self._worker_loop: asyncio.AbstractEventLoop | None = None
        self._worker_task: asyncio.Task | None = None
        self._running = False
        self._job_mode: JobMode = ""
        self._pending_confirm: threading.Event | None = None
        self._confirm_kind: str = "receipts"
        self._pending_recovery: threading.Event | None = None
        self._recovery_choice: str = "exit"
        self._subprocess: subprocess.Popen[str] | None = None
        self._status = "Готов к работе"

    def set_window(self, window: Any) -> None:
        self._window = window

    def _push_log_event(self, event: dict[str, Any]) -> None:
        if not event:
            return
        try:
            self._log_queue.put_nowait(event)
        except queue.Full:
            # UI не читает быстрее, чем пишем — роняем старое, не растим RAM.
            try:
                self._log_queue.get_nowait()
            except Exception:
                pass
            try:
                self._log_queue.put_nowait(event)
            except Exception:
                pass

    def _push_log(
        self,
        message: str,
        *,
        level: str = "info",
        service: str = "gui",
        status: str = "",
    ) -> None:
        raw = str(message or "").strip()
        if not raw:
            return
        # Строки decline/redirect скрипта: [INFO]/[OK]/[WARN]/[ERROR]
        msg = raw
        lvl = level
        st = status
        if raw.startswith("[ERROR]"):
            lvl = "error"
            st = st or "error"
            msg = raw[7:].strip()
        elif raw.startswith("[WARN]"):
            lvl = "warning"
            st = st or "warning"
            msg = raw[6:].strip()
        elif raw.startswith("[OK]"):
            lvl = "info"
            st = st or "ok"
            msg = raw[4:].strip()
        elif raw.startswith("[INFO]"):
            msg = raw[6:].strip()
        elif raw.startswith("[ALERT]"):
            lvl = "error"
            st = st or "alert"
            msg = raw[7:].strip()
        if not msg:
            return
        self._push_log_event(
            make_event(msg, level=lvl, service=service, status=st)
        )

    def _ok(self, **extra: Any) -> dict[str, Any]:
        return {"ok": True, **extra}

    def _err(self, message: str) -> dict[str, Any]:
        return {"ok": False, "error": message}

    def _notify_ui(self, script: str) -> None:
        if self._window is None:
            return
        try:
            self._window.evaluate_js(script)
        except Exception:
            pass

    def _completion_progress(self, payload: dict[str, Any]) -> None:
        self._notify_ui(f"updateReceiptProgress({json.dumps(payload)});")

    def _pipeline_progress(self, payload: dict[str, Any]) -> None:
        self._notify_ui(f"updatePipelineProgress({json.dumps(payload)});")

    def _cancel_alert(self, payload: dict[str, Any]) -> None:
        self._notify_ui(
            f"appendCancelAlert({json.dumps(payload, ensure_ascii=False)});"
        )
        line = " · ".join(
            p
            for p in (
                "ОТМЕНА СПИСАНИЯ",
                payload.get("card") or "",
                payload.get("amount") or "",
            )
            if p
        )
        match = str(payload.get("match_label") or "").strip()
        if match:
            line = f"{line} ≈ {match}"
        self._push_log(line, level="error", service="watch", status="alert")

    def _clear_receipt_progress(self) -> None:
        self._notify_ui("clearReceiptProgress();")

    def _clear_pipeline_progress(self) -> None:
        self._notify_ui("clearPipelineProgress();")

    def _focus_window(self) -> None:
        """Вывести окно Tzk на передний план (macOS: activate + makeKeyAndOrderFront)."""
        if self._window is None:
            return
        try:
            self._window.restore()
            self._window.show()
        except Exception:
            pass
        try:
            from AppKit import NSApp  # type: ignore

            NSApp.activateIgnoringOtherApps_(True)
            native = getattr(self._window, "native", None)
            if native is not None and hasattr(native, "makeKeyAndOrderFront_"):
                native.makeKeyAndOrderFront_(None)
        except Exception:
            pass

    def focus_window(self) -> dict[str, Any]:
        """JS-доступный фокус окна (ошибки / recovery)."""
        self._focus_window()
        return self._ok()

    def _minimize_window(self) -> None:
        if self._window is None:
            return
        try:
            self._window.minimize()
        except Exception:
            pass

    def _set_running(self, running: bool, mode: JobMode = "", *, keep_status: bool = False) -> None:
        self._running = running
        self._job_mode = mode if running else ""
        if not running and not keep_status:
            self._status = "Готов к работе"
        self._notify_ui(
            f"setRunning({json.dumps(running)}, {json.dumps(mode)}, "
            f"{json.dumps(keep_status)});"
            + (
                ""
                if keep_status
                else f"setStatus({json.dumps(self._status)});"
            )
        )

    def get_state(self) -> dict[str, Any]:
        created = ensure_local_configs()
        for rel in created:
            self._push_log(f"Создан {rel} из примера — поправь под себя", service="gui")
        cfg = load_config()
        pipe = cfg.get("pipeline") or {}
        val = cfg.get("validation") or {}
        redir = redirect_filter_settings()
        redir_bins = redirect_bin_settings()
        redir_amt = redirect_amount_settings()
        bins = decline_bin_settings()
        amounts = decline_amount_settings()
        pipe_bins = pipeline_bin_settings()
        adb_text, adb_ok = _adb_status_text()
        serial = bank_settings(cfg).get("adb_serial") or ""
        return {
            "max_deals": int(pipe.get("max_deals_per_run", 5)),
            "max_empty_list_passes": int(pipe.get("max_empty_list_passes", 2)),
            "min_amount": str(val.get("min_amount", "") or ""),
            "max_amount": str(val.get("max_amount", "") or ""),
            "allow_visa": bool(val.get("allow_visa", True)),
            "allow_mastercard": bool(val.get("allow_mastercard", False)),
            "from_pending": bool(pipe.get("from_pending", False)),
            "pipeline_bin_list": list(PIPELINE_BIN_PREFIXES),
            "pipeline_bin_toggles": pipe_bins,
            "redirect_skip_bog": bool(redir.get("skip_bog", False)),
            "redirect_visa_only": bool(redir.get("visa_only", False)),
            "redirect_max_remaining": bool(redir.get("max_remaining", False)),
            "redirect_bin_list": list(REDIRECT_BIN_PREFIXES),
            "redirect_bin_toggles": redir_bins,
            "redirect_max_per_run": redir_amt.get("max_per_run", "5"),
            "redirect_min_amount": redir_amt.get("min_amount", ""),
            "redirect_max_amount": redir_amt.get("max_amount", ""),
            "decline_bin_list": list(DECLINE_BIN_PREFIXES),
            "decline_bin_toggles": bins,
            "decline_tbc": decline_tbc_enabled(),
            "decline_max_per_run": decline_max_per_run(),
            "decline_min_amount": amounts.get("min_amount", ""),
            "decline_max_amount": amounts.get("max_amount", ""),
            "screens_dir": str(proofs_dir(cfg)),
            "videos_dir": str(videos_dir(cfg)),
            "video_min_usdt": float(
                (cfg.get("completion") or {}).get("video_min_usdt", 225.0)
            ),
            "adb_device": adb_text,
            "adb_ok": adb_ok,
            "adb_serial": str(serial),
            "status": self._status,
            "running": self._running,
            "job_mode": self._job_mode,
            "confirm_enabled": self._pending_confirm is not None
            and not self._pending_confirm.is_set(),
            "recovery_enabled": self._pending_recovery is not None
            and not self._pending_recovery.is_set(),
            "app_version": read_version(),
            "agent_configured": self._agent_configured(),
            "agent_model": self._agent_model(),
        }

    def poll_logs(self) -> list[dict[str, Any]]:
        """Структурированные события журнала (для interactive logs table)."""
        events: list[dict[str, Any]] = []
        while True:
            try:
                item = self._log_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, dict):
                events.append(item)
            # старые строковые записи игнорируем — журнал только структурированный
        return events

    def save_settings(
        self,
        max_deals: int,
        min_amount: str = "",
        max_amount: str = "",
        allow_visa: bool = True,
        allow_mastercard: bool = False,
        max_empty_list_passes: int | None = None,
        from_pending: bool = False,
        pipeline_bin_prefixes: list[str] | str | None = None,
    ) -> dict[str, Any]:
        try:
            min_amt = self._parse_amount(min_amount)
            max_amt = self._parse_amount(max_amount)
            empty_passes = (
                int(max_empty_list_passes)
                if max_empty_list_passes is not None
                else int((load_config().get("pipeline") or {}).get("max_empty_list_passes", 2))
            )
            apply_gui_settings(
                max_deals=int(max_deals),
                min_amount=min_amt,
                max_amount=max_amt,
                allow_visa=bool(allow_visa),
                allow_mastercard=bool(allow_mastercard),
                max_empty_list_passes=empty_passes,
                from_pending=bool(from_pending),
            )
            if pipeline_bin_prefixes is not None:
                if isinstance(pipeline_bin_prefixes, str):
                    raw_pb: list[Any] = pipeline_bin_prefixes.split(",")
                elif isinstance(pipeline_bin_prefixes, (list, tuple)):
                    raw_pb = list(pipeline_bin_prefixes)
                else:
                    raw_pb = []
                wanted = {
                    "".join(ch for ch in str(x) if ch.isdigit())
                    for x in raw_pb
                    if str(x).strip()
                }
                apply_pipeline_bin_filters(
                    prefixes=[p for p in PIPELINE_BIN_PREFIXES if p in wanted]
                )
            brands = []
            if allow_visa:
                brands.append("Visa")
            if allow_mastercard:
                brands.append("MC")
            saved_bins = pipeline_bin_settings()
            active_bins = [p for p in PIPELINE_BIN_PREFIXES if saved_bins.get(p)]
            mode = "pending→Approve→банк→чеки" if from_pending else "new→Accept→банк"
            msg = (
                f"[OK] Сохранено: {max_deals} сделок, "
                f"пустых кругов списка ≤ {empty_passes}, режим: {mode}"
            )
            if min_amt is not None or max_amt is not None:
                msg += f", сумма {min_amt or '—'}–{max_amt or '—'}"
            msg += f", карты: {', '.join(brands) if brands else 'нет'}"
            if active_bins:
                msg += f", BIN: {', '.join(active_bins)}"
            return self._ok(message=msg + "\n")
        except (ValueError, TypeError) as exc:
            return self._err(f"Некорректное значение: {exc}")

    def save_redirect_filters(
        self,
        skip_bog: bool = False,
        visa_only: bool = False,
        max_remaining: bool = False,
        redirect_prefixes: list[str] | str | None = None,
    ) -> dict[str, Any]:
        """Сохранить фильтры редиректа локально (runtime/deals_ui.yaml)."""
        try:
            ensure_local_configs()
            saved = apply_redirect_filters(
                skip_bog=bool(skip_bog),
                visa_only=bool(visa_only),
                max_remaining=bool(max_remaining),
            )
            if redirect_prefixes is not None:
                if isinstance(redirect_prefixes, str):
                    raw_rp: list[Any] = redirect_prefixes.split(",")
                elif isinstance(redirect_prefixes, (list, tuple)):
                    raw_rp = list(redirect_prefixes)
                else:
                    raw_rp = []
                wanted = {
                    "".join(ch for ch in str(x) if ch.isdigit())
                    for x in raw_rp
                    if str(x).strip()
                }
                apply_redirect_bin_filters(
                    prefixes=[p for p in REDIRECT_BIN_PREFIXES if p in wanted]
                )
            parts = []
            if saved.get("skip_bog"):
                parts.append("пропуск BoG")
            if saved.get("visa_only"):
                parts.append("только Visa")
            if saved.get("max_remaining"):
                parts.append(f"остаток < {REDIRECT_MAX_REMAINING_HOURS:g}ч")
            hint = ", ".join(parts) if parts else "выключены"
            return self._ok(message=f"[OK] Фильтры редиректа: {hint}\n")
        except Exception as exc:
            return self._err(f"Не удалось сохранить фильтры: {exc}")

    def start_login(self) -> dict[str, Any]:
        if self._running:
            return self._err("Уже выполняется")
        self._status = "Открываю окно входа…"
        self._set_running(True, "login")
        self._push_log("Вход в PlatCore", service="platcore", status="section")
        self._start_worker(run_login, "login")
        return self._ok()

    def start_pipeline(
        self,
        max_deals: int | None = None,
        min_amount: str = "",
        max_amount: str = "",
        allow_visa: bool = True,
        allow_mastercard: bool = False,
        max_empty_list_passes: int | None = None,
        from_pending: bool | None = None,
        pipeline_bin_prefixes: list[str] | str | None = None,
    ) -> dict[str, Any]:
        if self._running:
            return self._err("Уже выполняется")
        try:
            cfg = load_config()
            pipe = cfg.get("pipeline") or {}
            deals = int(max_deals or pipe.get("max_deals_per_run", 5))
            empty_passes = int(
                max_empty_list_passes
                if max_empty_list_passes is not None
                else pipe.get("max_empty_list_passes", 2)
            )
            pending = (
                bool(from_pending)
                if from_pending is not None
                else bool(pipe.get("from_pending", False))
            )
            apply_gui_settings(
                max_deals=deals,
                min_amount=self._parse_amount(min_amount),
                max_amount=self._parse_amount(max_amount),
                allow_visa=bool(allow_visa),
                allow_mastercard=bool(allow_mastercard),
                max_empty_list_passes=empty_passes,
                from_pending=pending,
            )
            if pipeline_bin_prefixes is not None:
                if isinstance(pipeline_bin_prefixes, str):
                    raw_pb: list[Any] = pipeline_bin_prefixes.split(",")
                elif isinstance(pipeline_bin_prefixes, (list, tuple)):
                    raw_pb = list(pipeline_bin_prefixes)
                else:
                    raw_pb = []
                wanted = {
                    "".join(ch for ch in str(x) if ch.isdigit())
                    for x in raw_pb
                    if str(x).strip()
                }
                apply_pipeline_bin_filters(
                    prefixes=[p for p in PIPELINE_BIN_PREFIXES if p in wanted]
                )
        except (ValueError, TypeError) as exc:
            return self._err(f"Некорректное значение: {exc}")
        active_bins = [
            p for p in PIPELINE_BIN_PREFIXES if pipeline_bin_settings().get(p)
        ]
        mode = "pending→Approve→банк→чеки" if pending else "Accept→банк→чеки"
        self._status = "Обрабатываю сделки…"
        self._set_running(True, "pipeline")
        bin_note = f", BIN {', '.join(active_bins)}" if active_bins else ""
        self._push_log(
            f"Запуск цикла ({mode}, до {deals} сделок, стоп после {empty_passes} пустых кругов{bin_note})",
            service="pipeline",
            status="section",
        )
        self._start_worker(run_pipeline, "pipeline")
        return self._ok()

    def start_accept_names(
        self,
        max_deals: int | float | str | None = None,
        min_amount: int | float | str | None = None,
        max_amount: int | float | str | None = None,
    ) -> dict[str, Any]:
        if self._running:
            return self._err("Уже выполняется")
        try:
            n = int(max_deals) if max_deals not in (None, "") else ACCEPT_NAMES_DEFAULT_MAX
        except (TypeError, ValueError):
            return self._err("Количество: 1–50")
        n = max(1, min(50, n))
        try:
            min_a = (
                self._parse_amount(str(min_amount))
                if min_amount not in (None, "")
                else None
            )
            max_a = (
                self._parse_amount(str(max_amount))
                if max_amount not in (None, "")
                else None
            )
        except (TypeError, ValueError) as exc:
            return self._err(f"Некорректная сумма USDT: {exc}")
        amt_bits = []
        if min_a is not None:
            amt_bits.append(f"от {min_a:g}")
        if max_a is not None:
            amt_bits.append(f"до {max_a:g}")
        amt_note = f" · {' '.join(amt_bits)} USDT" if amt_bits else ""
        self._status = f"Принимаю сделки (owner = sender, до {n})…"
        self._set_running(True, "accept_names")
        self._push_log(
            f"Accept по именам: до {n}{amt_note}, только PUT /accept",
            service="pipeline",
            status="section",
        )

        async def _job() -> None:
            from platcore.api_accept import accept_matching_names_loop

            cfg = load_config()
            payload = await accept_matching_names_loop(
                cfg,
                max_deals=n,
                min_amount=min_a,
                max_amount=max_a,
            )
            self._decline_result(payload)

        self._start_worker(_job, "accept_names")
        return self._ok()

    def start_decline(
        self,
        prefixes: list[str] | str | None = None,
        tbc: bool = False,
        max_per_run: int | float | str | None = None,
        min_amount: int | float | str | None = None,
        max_amount: int | float | str | None = None,
        bank: str | list[str] | None = None,
        max_remaining: bool = False,
        max_remaining_hours: float | None = None,
        card_prefixes: list[str] | str | None = None,
        all_cards: bool = False,
        visa_only: bool = False,
        mastercard_only: bool = False,
    ) -> dict[str, Any]:
        # pywebview: start_decline(["558328", …]) / start_decline(list, tbc)
        if isinstance(prefixes, bool) and bank is None:
            tbc = bool(prefixes)
            prefixes = None
        if isinstance(bank, (list, tuple)):
            prefixes = list(bank)
            bank = None
        elif isinstance(bank, str) and bank.lower() in ("tbc", "bog") and not prefixes:
            pass
        if isinstance(prefixes, str) and prefixes.lower() in ("tbc", "bog"):
            bank = prefixes
            prefixes = None
        if isinstance(prefixes, str):
            raw_pref: list[Any] = prefixes.split(",")
        elif isinstance(prefixes, (list, tuple)):
            raw_pref = list(prefixes)
        else:
            raw_pref = []
        wanted = {
            "".join(ch for ch in str(x) if ch.isdigit())
            for x in raw_pref
            if str(x).strip()
        }
        bins = [p for p in DECLINE_BIN_PREFIXES if p in wanted]
        include_tbc = bool(tbc)
        raw_card: list[Any]
        if isinstance(card_prefixes, str):
            raw_card = card_prefixes.split(",")
        elif isinstance(card_prefixes, (list, tuple)):
            raw_card = list(card_prefixes)
        else:
            raw_card = []
        from agent.bin_resolve import merge_decline_bins_and_prefixes

        _bins2, card_prefs = merge_decline_bins_and_prefixes([], raw_card)
        if not bins and not include_tbc and not card_prefs:
            if all_cards or visa_only or mastercard_only:
                pass
            elif bank:
                return self._start_decline_or_redirect(
                    redirect=False,
                    decline_bank=str(bank or "tbc"),
                )
            return self._err("Включи TBC, BIN, префикс карты (5598…) или Visa/MC")
        if visa_only and mastercard_only:
            return self._err("Нельзя Visa и Mastercard одновременно")
        limit = (
            0
            if max_per_run in (0, "0", 0.0)
            else clamp_decline_limit(
                max_per_run if max_per_run not in (None, "") else decline_max_per_run()
            )
        )
        try:
            min_a = (
                self._parse_amount(str(min_amount))
                if min_amount not in (None, "")
                else None
            )
            max_a = (
                self._parse_amount(str(max_amount))
                if max_amount not in (None, "")
                else None
            )
        except (TypeError, ValueError) as exc:
            return self._err(f"Некорректная сумма: {exc}")
        try:
            apply_decline_bin_filters(
                prefixes=bins,
                tbc=include_tbc,
                max_per_run=limit,
                min_amount=min_a,
                max_amount=max_a,
                clear_min_amount=min_a is None,
                clear_max_amount=max_a is None,
            )
        except Exception:
            pass
        return self._start_decline_or_redirect(
            redirect=False,
            decline_prefixes=bins,
            decline_card_prefixes=card_prefs,
            decline_tbc=include_tbc,
            max_per_run=limit,
            min_amount=min_a,
            max_amount=max_a,
            max_remaining=bool(max_remaining),
            max_remaining_hours=max_remaining_hours,
            all_cards=bool(all_cards) or bool(visa_only) or bool(mastercard_only),
            visa_only=bool(visa_only),
            mastercard_only=bool(mastercard_only),
        )

    def start_redirect(
        self,
        trader_ids: list[str] | str | None = None,
        max_per_run: int | float | str | None = None,
        min_amount: int | float | str | None = None,
        max_amount: int | float | str | None = None,
        deal_status: str | None = None,
        skip_bog: bool = False,
        visa_only: bool = False,
        mastercard_only: bool = False,
        max_remaining: bool = False,
        redirect_prefixes: list[str] | str | None = None,
        redirect_card_prefixes: list[str] | str | None = None,
        max_remaining_hours: float | None = None,
    ) -> dict[str, Any]:
        """Редирект сделок: сумма + лимит, выбранные traderId равномерно.

        deal_status: new (по умолчанию) или pending.
        По умолчанию все подряд. skip_bog=True — не редиректить BOG/548888….
        visa_only=True — только карты Visa (4…).
        mastercard_only=True — только Mastercard (2…/5…).
        max_remaining=True — только Time remaining < 1ч (expiredAt).
        """
        # list[str] или comma-string (старый React join) — не итерировать str по символам
        if isinstance(trader_ids, str):
            raw_ids: list[Any] = trader_ids.split(",")
        elif isinstance(trader_ids, (list, tuple)):
            raw_ids = list(trader_ids)
        else:
            raw_ids = []
        ids = [str(x).strip() for x in raw_ids if str(x).strip()]
        if not ids:
            return self._err("Выбери хотя бы один аккаунт (104.1 / 104.2 / 104.3)")
        if visa_only and mastercard_only:
            return self._err("Нельзя Visa и Mastercard одновременно")
        status = str(deal_status or "new").strip().lower() or "new"
        if status not in ("new", "pending"):
            return self._err("deal_status: только new или pending")
        try:
            max_n = int(max_per_run) if max_per_run not in (None, "") else None
            min_a = (
                float(min_amount) if min_amount not in (None, "") else None
            )
            max_a = (
                float(max_amount) if max_amount not in (None, "") else None
            )
        except (TypeError, ValueError) as exc:
            return self._err(f"Некорректные параметры редиректа: {exc}")
        if max_n is not None and max_n < 0:
            return self._err("Количество редиректов не может быть отрицательным")
        if isinstance(redirect_prefixes, str):
            raw_rp: list[Any] = redirect_prefixes.split(",")
        elif isinstance(redirect_prefixes, (list, tuple)):
            raw_rp = list(redirect_prefixes)
        else:
            raw_rp = []
        rp_wanted = {
            "".join(ch for ch in str(x) if ch.isdigit())
            for x in raw_rp
            if str(x).strip()
        }
        redirect_bins = [p for p in REDIRECT_BIN_PREFIXES if p in rp_wanted]
        raw_rc: list[Any]
        if isinstance(redirect_card_prefixes, str):
            raw_rc = redirect_card_prefixes.split(",")
        elif isinstance(redirect_card_prefixes, (list, tuple)):
            raw_rc = list(redirect_card_prefixes)
        else:
            raw_rc = []
        from agent.bin_resolve import merge_redirect_bins_and_prefixes

        _rb2, redirect_card_prefs = merge_redirect_bins_and_prefixes([], raw_rc)
        explicit_bins = bool(redirect_bins or redirect_card_prefs or raw_rp)
        filter_only = bool(
            visa_only
            or mastercard_only
            or skip_bog
            or max_remaining
            or min_a is not None
            or max_a is not None
        )
        try:
            apply_redirect_filters(
                skip_bog=bool(skip_bog),
                visa_only=bool(visa_only),
                max_remaining=bool(max_remaining),
            )
            if explicit_bins:
                apply_redirect_bin_filters(prefixes=redirect_bins)
            apply_redirect_amounts(
                max_per_run=max_n,
                min_amount=min_a,
                max_amount=max_a,
                clear_min_amount=min_a is None,
                clear_max_amount=max_a is None,
            )
        except Exception:
            pass
        if not explicit_bins and not filter_only:
            saved_bins = redirect_bin_settings()
            redirect_bins = [p for p in REDIRECT_BIN_PREFIXES if saved_bins.get(p)]
        return self._start_decline_or_redirect(
            redirect=True,
            trader_ids=ids,
            max_per_run=max_n,
            min_amount=min_a,
            max_amount=max_a,
            deal_status=status,
            skip_bog=bool(skip_bog),
            visa_only=bool(visa_only),
            mastercard_only=bool(mastercard_only),
            max_remaining=bool(max_remaining),
            redirect_prefixes=redirect_bins,
            redirect_card_prefixes=redirect_card_prefs,
            max_remaining_hours=max_remaining_hours,
        )

    @staticmethod
    def _agent_configured() -> bool:
        from agent.config import agent_configured

        return agent_configured()

    @staticmethod
    def _agent_model() -> str:
        from agent.config import agent_settings

        return str(agent_settings().get("model") or "")

    def _agent_ui_context(self, override: dict[str, Any] | None = None) -> dict[str, Any]:
        st = self.get_state()
        decline_bins = [
            p
            for p in (st.get("decline_bin_list") or [])
            if (st.get("decline_bin_toggles") or {}).get(p)
        ]
        redirect_bins = [
            p
            for p in (st.get("redirect_bin_list") or [])
            if (st.get("redirect_bin_toggles") or {}).get(p)
        ]
        traders: list[dict[str, str]] = []
        selected_ids: list[str] = []
        try:
            import sys

            decline_dir = str(DECLINE_DIR)
            if decline_dir not in sys.path:
                sys.path.insert(0, decline_dir)
            import decline_by_bank_api as dapi

            cfg = load_config()
            for label, tid in dapi._redirect_traders(cfg):
                traders.append({"label": label, "id": tid})
        except Exception:
            traders = []
        ctx = {
            "decline_bins": decline_bins,
            "decline_tbc": bool(st.get("decline_tbc")),
            "decline_min_amount": st.get("decline_min_amount") or "",
            "decline_max_amount": st.get("decline_max_amount") or "",
            "redirect_bins": redirect_bins,
            "redirect_skip_bog": bool(st.get("redirect_skip_bog")),
            "redirect_visa_only": bool(st.get("redirect_visa_only")),
            "redirect_max_remaining": bool(st.get("redirect_max_remaining")),
            "redirect_min_amount": st.get("redirect_min_amount") or "",
            "redirect_max_amount": st.get("redirect_max_amount") or "",
            "redirect_selected_trader_ids": selected_ids,
            "available_decline_bins": list(DECLINE_BIN_PREFIXES),
            "available_redirect_bins": list(REDIRECT_BIN_PREFIXES),
            "available_traders": traders,
        }
        if isinstance(override, dict):
            ctx.update(override)
        return ctx

    def _ensure_agent_trace(self) -> None:
        if getattr(self, "_agent_trace_registered", False):
            return
        from agent.trace import register_trace_sink

        register_trace_sink(lambda msg: self._push_log(msg, service="agent"))
        self._agent_trace_registered = True

    def agent_parse(
        self,
        text: str = "",
        ui_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from agent.history import lookup
        from agent.parser import parse_command_detailed
        from agent.trace import agent_trace

        self._ensure_agent_trace()
        cleaned = str(text or "").strip()
        hit = lookup(cleaned)
        cache_hit = bool(hit and isinstance(hit.get("plan"), dict))
        if not self._agent_configured() and not cache_hit:
            return self._err(
                "Gemini API ключ не задан — добавь agent.gemini_api_key в config.yaml"
            )
        try:
            ctx = self._agent_ui_context(ui_context)
            plan, meta = parse_command_detailed(cleaned, ctx)
            usage = meta.get("usage") or {}
            cached = bool(meta.get("cached"))
            if cached:
                debug = [
                    "Источник: история (кеш) — Gemini не вызывался",
                    f"Plan: {plan.human_summary()}",
                ]
                agent_trace(f"parse OK · cache HIT · {plan.human_summary()}")
                self._push_log(
                    f"AI из истории: {plan.human_summary()}",
                    service="agent",
                    status="section",
                )
            else:
                debug = [
                    f"Gemini model: {meta.get('model')}",
                    f"Tokens: prompt={usage.get('promptTokenCount')} "
                    f"out={usage.get('candidatesTokenCount')} "
                    f"total={usage.get('totalTokenCount')}",
                    f"Plan: {plan.human_summary()}",
                ]
                agent_trace(f"parse OK · total tokens={usage.get('totalTokenCount')}")
                self._push_log(
                    f"AI разбор: {plan.human_summary()}",
                    service="agent",
                    status="section",
                )
            return {
                "ok": True,
                "plan": plan.to_dict(),
                "summary": plan.human_summary(),
                "confidence": plan.confidence,
                "cached": cached,
                "debug": debug,
                "usage": usage,
            }
        except Exception as exc:
            traceback.print_exc()
            return self._err(str(exc))

    def agent_history(self, limit: int = 30) -> dict[str, Any]:
        from agent.history import list_history

        return {"ok": True, "items": list_history(limit=limit)}

    def agent_history_clear(self) -> dict[str, Any]:
        from agent.history import clear_history

        n = clear_history(keep_favorites=True)
        self._push_log(
            f"AI история очищена ({n}, избранные сохранены)",
            service="agent",
            status="section",
        )
        return {"ok": True, "cleared": n}

    def agent_history_remove(self, text: str = "") -> dict[str, Any]:
        from agent.history import remove_entry

        ok = remove_entry(str(text or ""))
        return {"ok": True, "removed": ok}

    def agent_history_favorite(
        self, text: str = "", favorite: bool = True
    ) -> dict[str, Any]:
        from agent.history import set_favorite

        ok = set_favorite(str(text or ""), bool(favorite))
        return {"ok": True, "updated": ok, "favorite": bool(favorite)}

    def agent_preview(
        self,
        plan: dict[str, Any] | None = None,
        ui_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from agent.deals_query import preview_plan_sync
        from agent.schema import ActionPlan
        from agent.trace import agent_trace

        self._ensure_agent_trace()
        if not isinstance(plan, dict):
            return self._err("Нет plan для preview")
        try:
            merged = ActionPlan.from_dict(plan).merge_agent_context(
                self._agent_ui_context(ui_context)
            ).finalize()
            err = merged.validate()
            if err:
                return self._err(err)
            payload = preview_plan_sync(merged)
            debug = [
                f"Preview: {payload.get('summary')}",
                f"Token source: {payload.get('token_source')}",
            ]
            for step in payload.get("steps") or []:
                if isinstance(step, dict):
                    line = f"{step.get('step')}: {step.get('detail')}"
                    debug.append(line)
                    agent_trace(f"preview · {line}")
                    self._push_log(
                        f"AI preview · {line}",
                        service="agent",
                    )
            agent_trace(f"preview OK · matched={payload.get('matched')}")
            self._push_log(
                str(payload.get("summary") or "AI preview готов"),
                service="agent",
                status="section",
            )
            return {"ok": True, "debug": debug, **payload}
        except SystemExit:
            return self._err(
                "Нет токена PlatCore. Залогинься через «Вход» или задай PLATCORE_TOKEN."
            )
        except Exception as exc:
            traceback.print_exc()
            from core.validators import PanicError

            if isinstance(exc, PanicError):
                return self._err(str(exc))
            return self._err(str(exc))

    def agent_execute(
        self,
        plan: dict[str, Any] | None = None,
        ui_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from agent.executor import execute_plan
        from agent.schema import ActionPlan

        if self._running:
            return self._err("Уже выполняется другая задача")
        if not isinstance(plan, dict):
            return self._err("Нет plan для execute")
        try:
            merged = ActionPlan.from_dict(plan).merge_agent_context(
                self._agent_ui_context(ui_context)
            ).finalize()
            err = merged.validate()
            if err:
                return self._err(err)
            self._push_log(
                f"AI запуск: {merged.human_summary()}",
                service="agent",
                status="section",
            )
            return execute_plan(self, merged)
        except Exception as exc:
            traceback.print_exc()
            return self._err(str(exc))

    def _start_decline_or_redirect(
        self,
        *,
        redirect: bool,
        trader_ids: list[str] | None = None,
        max_per_run: int | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        deal_status: str = "new",
        decline_bank: str = "tbc",
        decline_prefixes: list[str] | None = None,
        decline_card_prefixes: list[str] | None = None,
        decline_tbc: bool = False,
        skip_bog: bool = False,
        visa_only: bool = False,
        mastercard_only: bool = False,
        max_remaining: bool = False,
        redirect_prefixes: list[str] | None = None,
        redirect_card_prefixes: list[str] | None = None,
        max_remaining_hours: float | None = None,
        all_cards: bool = False,
    ) -> dict[str, Any]:
        if self._running:
            return self._err("Уже выполняется")
        ensure_local_configs()
        if not DECLINE_SCRIPT.is_file():
            return self._err(f"Не найден скрипт: {DECLINE_SCRIPT}")
        decline_cfg = DECLINE_DIR / "config.yaml"
        if not decline_cfg.is_file():
            return self._err(
                "Нет platcore-decline/config.yaml — должен создаться из "
                "config.example.yaml. Проверь, что example есть в репо."
            )
        if not PYTHON.is_file():
            return self._err(f"Не найден Python: {PYTHON}")
        mode: JobMode = "redirect" if redirect else "decline"
        bank_key = str(decline_bank or "tbc").strip().lower() or "tbc"
        if bank_key not in ("tbc", "bog"):
            bank_key = "tbc"
        prefixes = [
            "".join(ch for ch in str(p) if ch.isdigit())
            for p in (decline_prefixes or [])
            if str(p).strip()
        ]
        prefixes = [p for p in prefixes if p in DECLINE_BIN_PREFIXES]
        if redirect:
            status_word = "pending" if deal_status == "pending" else "new"
            filter_bits = []
            if skip_bog:
                filter_bits.append("пропуск BOG/548888")
            if visa_only:
                filter_bits.append("только Visa")
            if mastercard_only:
                filter_bits.append("только Mastercard")
            if max_remaining:
                filter_bits.append(
                    f"остаток < {(max_remaining_hours or REDIRECT_MAX_REMAINING_HOURS):g}ч"
                )
            rp = [
                p
                for p in REDIRECT_BIN_PREFIXES
                if p in (redirect_prefixes or [])
            ]
            rc = [
                "".join(ch for ch in str(p) if ch.isdigit())
                for p in (redirect_card_prefixes or [])
                if str(p).strip()
            ]
            if rp:
                filter_bits.append("BIN " + ", ".join(rp))
            if rc:
                filter_bits.append("карты " + ", ".join(p + "*" for p in rc))
            filter_note = ", ".join(filter_bits) if filter_bits else "все подряд"
            self._status = f"Редирект {status_word}-сделок…"
            self._push_log(
                f"Редирект {status_word}: traders={len(trader_ids or [])}, "
                f"{filter_note}",
                service="redirect",
                status="section",
            )
        else:
            card_prefs = [
                "".join(ch for ch in str(p) if ch.isdigit())
                for p in (decline_card_prefixes or [])
                if str(p).strip()
            ]
            if prefixes or decline_tbc or card_prefs:
                parts = []
                if decline_tbc:
                    parts.append("TBC")
                if prefixes:
                    parts.append(", ".join(prefixes))
                if card_prefs:
                    parts.append(" ".join(p + "*" for p in card_prefs))
                bank_word = " + ".join(parts)
                n = 0 if max_per_run == 0 else clamp_decline_limit(max_per_run)
                amt_bits = []
                if min_amount is not None:
                    amt_bits.append(f"от {min_amount:g}")
                if max_amount is not None:
                    amt_bits.append(f"до {max_amount:g}")
                amt_note = f" · {' '.join(amt_bits)} USDT" if amt_bits else ""
                limit_word = "все подходящие" if n == 0 else f"первые {n}"
                self._status = f"Отменяю сделки ({bank_word}, {limit_word})…"
                self._push_log(
                    f"Отмена: {bank_word} · сорт по remaining · {limit_word}{amt_note}",
                    service="decline",
                    status="section",
                )
            elif all_cards:
                n = 0 if max_per_run == 0 else clamp_decline_limit(max_per_run)
                amt_bits = []
                if min_amount is not None:
                    amt_bits.append(f"от {min_amount:g}")
                if max_amount is not None:
                    amt_bits.append(f"до {max_amount:g}")
                if max_remaining:
                    amt_bits.append(
                        f"остаток < {(max_remaining_hours or REDIRECT_MAX_REMAINING_HOURS):g}ч"
                    )
                scheme = (
                    "только Mastercard"
                    if mastercard_only
                    else "только Visa"
                    if visa_only
                    else "все карты"
                )
                amt_note = f" · {' '.join(amt_bits)}" if amt_bits else ""
                limit_word = "все подходящие" if n == 0 else f"первые {n}"
                self._status = f"Отменяю сделки ({scheme}, {limit_word})…"
                self._push_log(
                    f"Отмена: {scheme} · сорт по remaining · {limit_word}{amt_note}",
                    service="decline",
                    status="section",
                )
            else:
                bank_word = (
                    "Bank of Georgia / 548888"
                    if bank_key == "bog"
                    else "TBC / 4315"
                )
                self._status = f"Отменяю сделки ({bank_word})…"
                self._push_log(
                    f"Отмена по банку: {bank_word} ({bank_key})",
                    service="decline",
                    status="section",
                )
        self._set_running(True, mode)
        self._worker = threading.Thread(
            target=self._run_decline_thread,
            kwargs={
                "redirect": redirect,
                "trader_ids": trader_ids,
                "max_per_run": max_per_run,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "deal_status": deal_status,
                "decline_bank": bank_key,
                "decline_prefixes": prefixes,
                "decline_card_prefixes": [
                    "".join(ch for ch in str(p) if ch.isdigit())
                    for p in (decline_card_prefixes or [])
                    if str(p).strip()
                ],
                "decline_tbc": bool(decline_tbc),
                "skip_bog": skip_bog,
                "visa_only": visa_only,
                "mastercard_only": mastercard_only,
                "max_remaining": max_remaining,
                "max_remaining_hours": max_remaining_hours,
                "redirect_prefixes": redirect_prefixes or [],
                "redirect_card_prefixes": [
                    "".join(ch for ch in str(p) if ch.isdigit())
                    for p in (redirect_card_prefixes or [])
                    if str(p).strip()
                ],
                "all_cards": bool(all_cards),
            },
            name=f"tzk-{mode}",
            daemon=True,
        )
        self._worker.start()
        return self._ok()

    def stop_job(self) -> dict[str, Any]:
        if not self._running:
            return self._ok()
        request_stop()
        try:
            from notify.cancel import stop_cancel_watch_now

            stop_cancel_watch_now()
        except Exception:
            pass
        if self._pending_confirm is not None:
            self._pending_confirm.set()
            self._pending_confirm = None
        if self._pending_recovery is not None:
            self._recovery_choice = "exit"
            self._pending_recovery.set()
            self._pending_recovery = None
            self._notify_ui("hideRecoveryPrompt();")
        self._status = "Останавливаю… закрываю браузер"
        self._notify_ui(
            f"setStatus({json.dumps(self._status)});"
            "hideRecoveryPrompt();"
        )
        self._push_log("Полная остановка: браузер и контекст…", service="gui")
        try:
            from core.hard_stop import kill_popen

            kill_popen(self._subprocess)
        except Exception:
            if self._subprocess is not None and self._subprocess.poll() is None:
                try:
                    self._subprocess.terminate()
                except Exception:
                    pass
        loop = self._worker_loop
        task = self._worker_task
        if loop is not None and task is not None and not task.done():
            loop.call_soon_threadsafe(task.cancel)
            try:
                from core.browser_session import force_close_browser

                fut = asyncio.run_coroutine_threadsafe(
                    force_close_browser(reason="stop_job"),
                    loop,
                )
                fut.result(timeout=1.5)
            except Exception:
                pass
        return self._ok()

    def confirm(self, kind: str = "receipts") -> dict[str, Any]:
        if self._pending_confirm is not None:
            self._confirm_kind = str(kind or "receipts").strip().lower() or "receipts"
            self._pending_confirm.set()
            self._pending_confirm = None
        return self._ok()

    def cancel_completion_deal(self, order_id: str) -> dict[str, Any]:
        """Отмена сделки без чека (dispute) — только в фазе ожидания чеков."""
        oid = self._resolve_completion_order_id(order_id)
        if not oid:
            return self._err("order_id пустой")
        if self._pending_confirm is None or self._pending_confirm.is_set():
            return self._err("Сейчас нельзя отменить — дождитесь шага чеков")
        if not is_completion_phase():
            return self._err("Отмена доступна только на шаге чеков")
        self._confirm_kind = f"cancel:{oid}"
        self._pending_confirm.set()
        self._pending_confirm = None
        return self._ok()

    def retry_completion_deal(self, order_id: str) -> dict[str, Any]:
        """Повтор Money sent для сделки с ошибкой (чек уже есть)."""
        oid = self._resolve_completion_order_id(order_id)
        if not oid:
            return self._err("order_id пустой")
        if self._pending_confirm is None or self._pending_confirm.is_set():
            return self._err("Сейчас нельзя повторить — дождитесь шага чеков")
        if not is_completion_phase():
            return self._err("Повтор доступен только на шаге чеков")
        self._confirm_kind = f"retry:{oid}"
        self._pending_confirm.set()
        self._pending_confirm = None
        return self._ok()

    def rescan_completion_deal(self, order_id: str) -> dict[str, Any]:
        """Сбросить чек у сделки — положить новый файл и снова «Загрузить»."""
        oid = self._resolve_completion_order_id(order_id)
        if not oid:
            return self._err("order_id пустой")
        if self._pending_confirm is None or self._pending_confirm.is_set():
            return self._err("Сейчас нельзя — дождитесь шага чеков")
        if not is_completion_phase():
            return self._err("Доступно только на шаге чеков")
        self._confirm_kind = f"retry:rescan:{oid}"
        self._pending_confirm.set()
        self._pending_confirm = None
        return self._ok()

    def _resolve_completion_order_id(self, raw: str) -> str:
        """Привести order_id к каноническому виду из активной сессии чеков."""
        oid = str(raw or "").strip()
        if not oid:
            return ""
        try:
            from completion.phase import get_active_completion_session
            from completion.session import find_session_deal

            session, _ = get_active_completion_session()
            deal = find_session_deal(session, oid)
            if deal and deal.order_id:
                return deal.order_id
        except Exception:
            pass
        return oid

    def preview_receipts(self) -> dict[str, Any]:
        """Dry-scan папки чеков: что уже найдено до нажатия «Загрузить»."""
        if not is_completion_phase():
            return {"ok": False, "error": "Фаза чеков не активна", "deals": []}
        try:
            from completion.phase import preview_receipt_readiness

            return preview_receipt_readiness()
        except Exception as exc:
            return {"ok": False, "error": str(exc), "deals": []}

    def recovery_continue(self) -> dict[str, Any]:
        return self._resolve_recovery("continue")

    def recovery_retry(self) -> dict[str, Any]:
        return self._resolve_recovery("retry")

    def recovery_exit(self) -> dict[str, Any]:
        return self._resolve_recovery("exit")

    def _resolve_recovery(self, choice: str) -> dict[str, Any]:
        self._recovery_choice = choice
        if self._pending_recovery is not None:
            self._pending_recovery.set()
            self._pending_recovery = None
        self._notify_ui("hideRecoveryPrompt();")
        return self._ok()

    def open_screens_folder(self) -> dict[str, Any]:
        cfg = load_config()
        subprocess.run(["open", str(proofs_dir(cfg))], check=False)
        return self._ok()

    def open_videos_folder(self) -> dict[str, Any]:
        cfg = load_config()
        subprocess.run(["open", str(videos_dir(cfg))], check=False)
        return self._ok()

    def check_adb(self) -> dict[str, Any]:
        """Проверка USB/adb устройства + папки скринов/видео на телефоне."""
        adb_text, adb_ok = _adb_status_text()
        report = f"ADB: {adb_text}\n"
        media: dict[str, Any] = {}
        if adb_ok:
            try:
                from device.phone_media import detect_phone_media_dirs

                dirs = detect_phone_media_dirs()
                media = dirs.to_dict()
                for line in dirs.summary_lines():
                    report += line + "\n"
            except Exception as exc:
                report += f"Медиа на телефоне: ошибка ({exc})\n"
                media = {"ok": False, "error": str(exc)}
        self._push_log(report, service="device")
        if adb_ok:
            return self._ok(
                message=report,
                adb_device=adb_text,
                adb_ok=True,
                phone_media=media,
            )
        return self._ok(
            message=report + "Подключи телефон: USB или Wi‑Fi debugging, `adb devices`.\n",
            adb_device=adb_text,
            adb_ok=False,
            needs_device=True,
            phone_media=media,
        )

    def get_update_status(self) -> dict[str, Any]:
        return self._ok(**update_status())

    def apply_app_update(self) -> dict[str, Any]:
        """Скачать последний код с GitHub. Не затирает config.yaml / .venv."""
        if self._running:
            return self._err("Сначала останови текущую задачу (Стоп), потом обновляй.")
        result = apply_update()
        if result.get("ok"):
            msg = (
                f"Обновление OK ({result.get('method')}). "
                f"Версия: {result.get('version_before', '?')} → {result.get('version', '?')}. "
            )
            if result.get("venv_ok"):
                msg += ".venv готов. "
            elif result.get("venv_error"):
                msg += f"Внимание venv: {result.get('venv_error')}. "
            msg += "Перезапусти сервер (↻), чтобы подхватить код.\n"
            self._push_log(msg, service="gui")
            return self._ok(message=msg, **{k: v for k, v in result.items() if k != "ok"})
        err = str(result.get("error") or "Не удалось обновить")
        self._push_log(f"Обновление: {err}", level="error", service="gui")
        return self._err(err)

    def _parse_amount(self, raw: str) -> float | None:
        text = str(raw).strip().replace(",", ".")
        if not text:
            return None
        return float(text)

    async def _gui_confirm(self, prompt: str) -> str:
        done = threading.Event()
        self._confirm_kind = "receipts"
        self._pending_confirm = done
        mode = self._job_mode
        short = prompt.replace("\n", " ").strip()
        self._status = short
        safe_prompt = json.dumps(short)
        safe_mode = json.dumps(mode)
        self._notify_ui(f"setConfirmPrompt({safe_prompt}, {safe_mode});")
        if mode == "pipeline" and is_bank_phase():
            enter_foreground()
        await asyncio.to_thread(done.wait)
        self._pending_confirm = None
        kind = self._confirm_kind or "receipts"
        if mode == "pipeline" and is_bank_phase():
            enter_background()
        return kind

    async def _gui_recovery(
        self,
        message: str,
        detail: str,
        hint: str,
        summary: dict[str, Any],
        allow_retry: bool,
    ) -> str:
        done = threading.Event()
        self._pending_recovery = done
        self._recovery_choice = "exit"
        self._status = message
        self._push_log(f"{message}: {detail}".strip(": "), level="error", service="gui", status="error")
        enter_foreground()
        self._focus_window()
        self._notify_ui(
            f"setRecoveryPrompt({json.dumps(message)}, "
            f"{json.dumps(detail)}, {json.dumps(hint)}, "
            f"{json.dumps(summary)}, {json.dumps(allow_retry)});"
        )
        await asyncio.to_thread(done.wait)
        self._pending_recovery = None
        if (
            self._recovery_choice in ("retry", "continue")
            and self._job_mode == "pipeline"
            and is_bank_phase()
        ):
            enter_background()
        return self._recovery_choice

    def _run_job_thread(
        self,
        coro_factory: Callable[[], object],
        mode: JobMode,
    ) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._worker_loop = loop
        set_confirm_handler(self._gui_confirm)
        set_recovery_handler(self._gui_recovery)
        set_completion_progress_handler(self._completion_progress)
        set_pipeline_progress_handler(self._pipeline_progress)
        try:
            from notify.cancel import set_cancel_handler

            set_cancel_handler(self._cancel_alert)
        except Exception:
            pass
        begin_job()

        async def _prepare() -> None:
            from core.browser_session import close_before_new_run

            await close_before_new_run()

        loop.run_until_complete(_prepare())

        set_gui_mode(True)
        reset_window_session()
        set_job_window_hooks(self._minimize_window, self._focus_window)

        stdout_prev = sys.stdout
        stderr_prev = sys.stderr
        redirector = LogRedirector(self._push_log_event)
        sys.stdout = redirector
        sys.stderr = redirector

        task = loop.create_task(coro_factory())  # type: ignore[arg-type]
        self._worker_task = task

        try:
            loop.run_until_complete(task)
            if not task.cancelled():
                self._push_log("Завершено", status="ok", service="gui")
        except asyncio.CancelledError:
            self._push_log("Остановлено", service="gui")
        except Exception:
            self._push_log(traceback.format_exc(), level="error", service="gui", status="error")
        finally:
            # Гарантия при стопе/ошибке: браузер не висит (headless).
            # Успех + exit_after_run=false — сессию не трогаем.
            try:
                from core.browser_session import force_close_browser
                from ui.job_control import is_stopped

                task_failed = False
                try:
                    task_failed = bool(
                        task.done()
                        and not task.cancelled()
                        and task.exception() is not None
                    )
                except Exception:
                    task_failed = True
                should_force = (
                    is_stopped() or task.cancelled() or task_failed
                )
                if should_force and not loop.is_closed():
                    loop.run_until_complete(
                        force_close_browser(reason="конец задачи")
                    )
            except Exception as close_exc:
                self._push_log(f"Закрытие браузера: {close_exc}", level="warning", service="gui")
            enter_foreground()
            set_gui_mode(False)
            clear_job_window_hooks()
            set_confirm_handler(None)
            set_recovery_handler(None)
            clear_completion_progress_handler()
            clear_pipeline_progress_handler()
            try:
                from notify.cancel import set_cancel_handler

                set_cancel_handler(None)
            except Exception:
                pass
            sys.stdout = stdout_prev
            sys.stderr = stderr_prev
            self._worker_loop = None
            self._worker_task = None
            try:
                loop.close()
            except Exception:
                pass
            self._set_running(False)
            self._notify_ui("hideRecoveryPrompt();")

    def _start_worker(
        self,
        coro_factory: Callable[[], object],
        mode: JobMode,
    ) -> None:
        self._worker = threading.Thread(
            target=lambda: self._run_job_thread(coro_factory, mode),
            name=f"tzk-{mode}",
            daemon=True,
        )
        self._worker.start()

    @staticmethod
    def _format_decline_summary(payload: dict[str, Any]) -> str:
        """Один человекочитаемый итог: сколько + какие сделки."""
        action = str(payload.get("action") or "cancel")
        deals = payload.get("deals") or []
        if not isinstance(deals, list):
            deals = []
        redirected = int(payload.get("redirected") or 0)
        cancelled = int(payload.get("cancelled") or 0)
        failed = int(payload.get("failed") or 0)
        total = int(payload.get("total") or len(deals))
        if action == "redirect":
            head = f"Редирект: {redirected}/{total}"
        elif action == "accept":
            accepted = int(payload.get("accepted") or 0)
            head = f"Принято: {accepted}/{total}"
        else:
            head = f"Отмена: {cancelled}/{total}"
        if failed:
            head += f", ошибок {failed}"
        if not deals:
            return str(payload.get("message") or head)
        lines = [head]
        for d in deals:
            if not isinstance(d, dict):
                continue
            mark = "✓" if d.get("ok") else "✗"
            card = str(d.get("card") or "????")
            holder = str(d.get("holder") or "—").strip() or "—"
            amount = str(d.get("amount") or "—")
            bank = str(d.get("bank") or "").strip()
            err = str(d.get("error") or "").strip()
            bit = f"{mark} {card}  {holder}  {amount}"
            if bank:
                bit += f"  → {bank}"
            if err:
                bit += f"  ({err})"
            lines.append(bit)
        return "\n".join(lines)

    def _decline_result(self, payload: dict[str, Any]) -> None:
        action = str(payload.get("action") or "cancel")
        default = {
            "redirect": "Редирект завершён",
            "accept": "Принятие завершено",
        }.get(action, "Отмена завершена")
        self._status = str(payload.get("message") or default)
        self._notify_ui(
            f"updateDeclineResult({json.dumps(payload, ensure_ascii=False)});"
            f"setStatus({json.dumps(self._status)});"
        )

    def _run_decline_thread(
        self,
        *,
        redirect: bool = False,
        trader_ids: list[str] | None = None,
        max_per_run: int | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        deal_status: str = "new",
        decline_bank: str = "tbc",
        decline_prefixes: list[str] | None = None,
        decline_card_prefixes: list[str] | None = None,
        decline_tbc: bool = False,
        skip_bog: bool = False,
        visa_only: bool = False,
        mastercard_only: bool = False,
        max_remaining: bool = False,
        redirect_prefixes: list[str] | None = None,
        redirect_card_prefixes: list[str] | None = None,
        max_remaining_hours: float | None = None,
        all_cards: bool = False,
    ) -> None:
        begin_job()
        saw_ui_result = False
        action = "redirect" if redirect else "cancel"
        svc = "redirect" if redirect else "decline"
        cmd = [str(PYTHON), str(DECLINE_SCRIPT)]
        if redirect:
            cmd.append("--redirect")
            status = str(deal_status or "new").strip().lower() or "new"
            if status != "new":
                cmd.extend(["--deal-status", status])
            for tid in trader_ids or []:
                cmd.extend(["--trader-id", tid])
            if max_per_run is not None:
                cmd.extend(["--max-per-run", str(int(max_per_run))])
            if min_amount is not None:
                cmd.extend(["--min-amount", str(min_amount)])
            if max_amount is not None:
                cmd.extend(["--max-amount", str(max_amount)])
            if skip_bog:
                cmd.append("--skip-bog")
            if visa_only:
                cmd.append("--visa-only")
            if mastercard_only:
                cmd.append("--mastercard-only")
            if max_remaining:
                cmd.append("--max-remaining")
                hours = max_remaining_hours or REDIRECT_MAX_REMAINING_HOURS
                cmd.extend(["--max-remaining-hours", str(hours)])
            rp = [
                p
                for p in REDIRECT_BIN_PREFIXES
                if p in (redirect_prefixes or [])
            ]
            rc = [
                "".join(ch for ch in str(p) if ch.isdigit())
                for p in (redirect_card_prefixes or [])
                if str(p).strip()
            ]
            for p in rp:
                cmd.extend(["--redirect-prefix", p])
            for p in rc:
                cmd.extend(["--redirect-card-prefix", p])
        else:
            prefixes = [
                "".join(ch for ch in str(p) if ch.isdigit())
                for p in (decline_prefixes or [])
                if str(p).strip()
            ]
            prefixes = [p for p in prefixes if p in DECLINE_BIN_PREFIXES]
            card_prefs = [
                "".join(ch for ch in str(p) if ch.isdigit())
                for p in (decline_card_prefixes or [])
                if str(p).strip()
            ]
            if prefixes or decline_tbc or card_prefs:
                for p in prefixes:
                    cmd.extend(["--prefix", p])
                for p in card_prefs:
                    cmd.extend(["--card-prefix", p])
                if decline_tbc:
                    cmd.append("--tbc")
                n = 0 if max_per_run == 0 else clamp_decline_limit(max_per_run)
                cmd.extend(["--max-per-run", str(n)])
                if min_amount is not None:
                    cmd.extend(["--min-amount", str(min_amount)])
                if max_amount is not None:
                    cmd.extend(["--max-amount", str(max_amount)])
                if max_remaining:
                    cmd.append("--max-remaining")
                    hours = max_remaining_hours or REDIRECT_MAX_REMAINING_HOURS
                    cmd.extend(["--max-remaining-hours", str(hours)])
                if visa_only:
                    cmd.append("--visa-only")
                if mastercard_only:
                    cmd.append("--mastercard-only")
            elif all_cards:
                n = 0 if max_per_run == 0 else clamp_decline_limit(max_per_run)
                cmd.append("--all-cards")
                cmd.extend(["--max-per-run", str(n)])
                if min_amount is not None:
                    cmd.extend(["--min-amount", str(min_amount)])
                if max_amount is not None:
                    cmd.extend(["--max-amount", str(max_amount)])
                if max_remaining:
                    cmd.append("--max-remaining")
                    hours = max_remaining_hours or REDIRECT_MAX_REMAINING_HOURS
                    cmd.extend(["--max-remaining-hours", str(hours)])
                if visa_only:
                    cmd.append("--visa-only")
                if mastercard_only:
                    cmd.append("--mastercard-only")
            else:
                bank = str(decline_bank or "tbc").strip().lower() or "tbc"
                if bank not in ("tbc", "bog"):
                    bank = "tbc"
                cmd.extend(["--bank", bank])
        cmd.append("--execute")
        try:
            self._notify_ui("clearDeclineResult();")
            self._subprocess = subprocess.Popen(
                cmd,
                cwd=str(DECLINE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            assert self._subprocess.stdout is not None
            # Детали скрипта — только в терминал; в журнал — один итог.
            # При падении сохраняем хвост ошибок для UI.
            err_tail: list[str] = []
            for line in self._subprocess.stdout:
                try:
                    sys.__stdout__.write(line)
                    sys.__stdout__.flush()
                except Exception:
                    pass
                text = line.rstrip("\n")
                low = text.lower()
                if (
                    "error" in low
                    or "traceback" in low
                    or "exception" in low
                    or text.startswith("SystemExit")
                    or "IndentationError" in text
                    or "SyntaxError" in text
                    or text.startswith("[ERROR]")
                ):
                    err_tail.append(text.strip())
                    if len(err_tail) > 8:
                        err_tail = err_tail[-8:]
                if not line.startswith("TZK_DECLINE_RESULT\t"):
                    continue
                raw = line.split("\t", 1)[1].strip()
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                saw_ui_result = True
                self._decline_result(payload)
                failed = int(payload.get("failed") or 0)
                self._push_log(
                    self._format_decline_summary(payload),
                    level="warning" if failed else "info",
                    service=svc,
                    status="warning" if failed else "ok",
                )
            code = self._subprocess.wait()
            done_word = "Редирект" if redirect else "Отмена"
            if code == 0:
                if not saw_ui_result:
                    empty = {
                        "phase": "done",
                        "action": action,
                        "cancelled": 0,
                        "redirected": 0,
                        "failed": 0,
                        "total": 0,
                        "message": f"{done_word}: подходящих сделок нет",
                        "deals": [],
                    }
                    self._decline_result(empty)
                    self._push_log(
                        empty["message"],
                        status="ok",
                        service=svc,
                    )
            else:
                detail = ""
                if err_tail:
                    detail = " — " + " | ".join(err_tail[-3:])
                msg = f"{done_word}: ошибка (код {code}){detail}"
                self._push_log(
                    msg,
                    level="error",
                    service=svc,
                    status="error",
                )
                if not saw_ui_result:
                    self._decline_result(
                        {
                            "phase": "done",
                            "action": action,
                            "cancelled": 0,
                            "redirected": 0,
                            "failed": 1,
                            "total": 0,
                            "message": msg,
                            "deals": [],
                        }
                    )
        except Exception:
            self._push_log(traceback.format_exc(), level="error", service="gui", status="error")
            self._decline_result(
                {
                    "phase": "done",
                    "action": action,
                    "cancelled": 0,
                    "redirected": 0,
                    "failed": 1,
                    "total": 0,
                    "message": (
                        "Ошибка при редиректе сделок"
                        if redirect
                        else "Ошибка при отмене сделок"
                    ),
                    "deals": [],
                }
            )
        finally:
            self._subprocess = None
            self._set_running(False, keep_status=True)

def main() -> None:
    try:
        import webview
    except ImportError:
        print("Нужен pywebview: pip install pywebview", file=sys.stderr)
        sys.exit(1)

    ui_path = WEB_UI if WEB_UI.is_file() else WEB_UI_LEGACY
    if not ui_path.is_file():
        print(
            f"Не найден UI: {WEB_UI} (собери: cd web_ui && npm run build)",
            file=sys.stderr,
        )
        sys.exit(1)

    api = TzkApi()
    window = webview.create_window(
        "TJS",
        url=ui_path.as_uri(),
        js_api=api,
        width=960,
        height=900,
        min_size=(720, 700),
        background_color="#f0fdfa",
    )
    api.set_window(window)
    webview.start()


if __name__ == "__main__":
    main()
