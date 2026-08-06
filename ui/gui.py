#!/usr/bin/env python3
"""tzk — графическая оболочка (вместо консоли)."""

from __future__ import annotations

import asyncio
import queue
import sys
import threading
import traceback
from typing import Callable, Literal

import tkinter as tk
from tkinter import messagebox, scrolledtext

from completion.registry import proofs_dir
from core.config import load_config
from ui.settings import apply_gui_settings
from ui.job_control import begin_job, request_stop
from pipeline.runner import run_login, run_pipeline
from ui.prompts import set_confirm_handler

JobMode = Literal["", "pipeline", "login"]

# Tk 8.5 (CLT Python на macOS) плохо рисует ttk — только tk-виджеты.
UI_BG = "#f2f2f7"
UI_FG = "#1d1d1f"
UI_ACCENT = "#007aff"
UI_BORDER = "#c7c7cc"
UI_LOG_BG = "#ffffff"
UI_FONT = "Helvetica"
UI_FONT_MONO = "Menlo"
UI_FONT_BOLD = (UI_FONT, 13, "bold")
UI_FONT_BODY = (UI_FONT, 12)
UI_FONT_SMALL = (UI_FONT, 11)
UI_FONT_LOG = (UI_FONT_MONO, 11)


class LogRedirector:
    def __init__(self, log_queue: queue.Queue[str]) -> None:
        self._queue = log_queue

    def write(self, text: str) -> None:
        if text:
            self._queue.put(text)

    def flush(self) -> None:
        pass


def _frame(parent: tk.Misc, **kwargs) -> tk.Frame:
    opts = {"bg": UI_BG}
    opts.update(kwargs)
    return tk.Frame(parent, **opts)


def _label(parent: tk.Misc, **kwargs) -> tk.Label:
    opts = {"bg": UI_BG, "fg": UI_FG, "font": UI_FONT_BODY}
    opts.update(kwargs)
    return tk.Label(parent, **opts)


def _button(parent: tk.Misc, **kwargs) -> tk.Button:
    opts = {
        "bg": "#ffffff",
        "fg": UI_FG,
        "activebackground": "#e5e5ea",
        "activeforeground": UI_FG,
        "relief": tk.GROOVE,
        "bd": 1,
        "padx": 10,
        "pady": 4,
        "font": UI_FONT_BODY,
        "cursor": "hand2",
    }
    opts.update(kwargs)
    return tk.Button(parent, **opts)


def _labelframe(parent: tk.Misc, text: str, **kwargs) -> tk.LabelFrame:
    opts = {
        "text": text,
        "bg": UI_BG,
        "fg": UI_FG,
        "font": UI_FONT_BODY,
        "bd": 1,
        "relief": tk.GROOVE,
        "padx": 10,
        "pady": 8,
    }
    opts.update(kwargs)
    return tk.LabelFrame(parent, **opts)


class TzkApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("tzk — PlatCore + Bank")
        self.root.minsize(560, 500)
        self.root.configure(bg=UI_BG)

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._confirm_requests: queue.Queue[tuple[str, threading.Event]] = queue.Queue()
        self._pending_confirm_done: threading.Event | None = None
        self._confirm_kind: str = "receipts"
        self._worker: threading.Thread | None = None
        self._worker_loop: asyncio.AbstractEventLoop | None = None
        self._worker_task: asyncio.Task | None = None
        self._running = False
        self._job_mode: JobMode = ""

        cfg = load_config()
        self._screens_dir = proofs_dir(cfg)
        pipe = cfg.get("pipeline") or {}
        val = cfg.get("validation") or {}

        header = _frame(root, padx=10, pady=10)
        header.pack(fill=tk.X)

        _label(
            header,
            text="PlatCore → Bank → Загрузки → Money sent",
            font=UI_FONT_BOLD,
        ).pack(anchor=tk.W)

        _label(
            header,
            text=f"Загрузки: {self._screens_dir}",
            font=UI_FONT_SMALL,
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 0))

        settings = _labelframe(root, text="Настройки", padx=10, pady=10)
        settings.pack(fill=tk.X, padx=10, pady=(4, 0))

        row1 = _frame(settings)
        row1.pack(fill=tk.X)

        _label(row1, text="Сделок за цикл:").pack(side=tk.LEFT)
        self.max_deals_var = tk.IntVar(
            value=int(pipe.get("max_deals_per_run", 5))
        )
        self.max_deals_spin = tk.Spinbox(
            row1,
            from_=1,
            to=50,
            width=5,
            textvariable=self.max_deals_var,
            font=UI_FONT_BODY,
            bg="#ffffff",
            fg=UI_FG,
            buttonbackground=UI_BG,
        )
        self.max_deals_spin.pack(side=tk.LEFT, padx=(6, 16))

        _label(row1, text="Пустых кругов:").pack(side=tk.LEFT)
        self.empty_passes_var = tk.IntVar(
            value=int(pipe.get("max_empty_list_passes", 2))
        )
        self.empty_passes_spin = tk.Spinbox(
            row1,
            from_=1,
            to=20,
            width=4,
            textvariable=self.empty_passes_var,
            font=UI_FONT_BODY,
            bg="#ffffff",
            fg=UI_FG,
            buttonbackground=UI_BG,
        )
        self.empty_passes_spin.pack(side=tk.LEFT, padx=(6, 16))

        _label(row1, text="USDT от:").pack(side=tk.LEFT)
        self.min_amount_var = tk.StringVar(
            value=str(val.get("min_amount", "") or "")
        )
        tk.Entry(
            row1,
            textvariable=self.min_amount_var,
            width=7,
            font=UI_FONT_BODY,
            bg="#ffffff",
            fg=UI_FG,
        ).pack(side=tk.LEFT, padx=(4, 12))

        _label(row1, text="до:").pack(side=tk.LEFT)
        self.max_amount_var = tk.StringVar(
            value=str(val.get("max_amount", "") or "")
        )
        tk.Entry(
            row1,
            textvariable=self.max_amount_var,
            width=7,
            font=UI_FONT_BODY,
            bg="#ffffff",
            fg=UI_FG,
        ).pack(side=tk.LEFT, padx=(4, 12))

        self.allow_visa_var = tk.BooleanVar(
            value=bool(val.get("allow_visa", True))
        )
        tk.Checkbutton(
            row1,
            text="Visa(4)",
            variable=self.allow_visa_var,
            font=UI_FONT_BODY,
            bg=UI_BG,
            fg=UI_FG,
            activebackground=UI_BG,
            selectcolor="#ffffff",
        ).pack(side=tk.LEFT, padx=(4, 4))

        self.allow_mc_var = tk.BooleanVar(
            value=bool(val.get("allow_mastercard", False))
        )
        tk.Checkbutton(
            row1,
            text="MC(5)",
            variable=self.allow_mc_var,
            font=UI_FONT_BODY,
            bg=UI_BG,
            fg=UI_FG,
            activebackground=UI_BG,
            selectcolor="#ffffff",
        ).pack(side=tk.LEFT, padx=(4, 12))

        self.save_btn = _button(
            row1,
            text="Сохранить",
            command=self._save_settings,
        )
        self.save_btn.pack(side=tk.LEFT)

        actions = _frame(root, padx=10, pady=(8, 4))
        actions.pack(fill=tk.X)

        self.login_btn = _button(
            actions,
            text="Логин PlatCore",
            command=self._on_login,
        )
        self.login_btn.pack(side=tk.LEFT)

        self.start_btn = _button(
            actions,
            text="Старт цикла",
            command=self._on_start,
        )
        self.start_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.stop_btn = _button(
            actions,
            text="Стоп",
            command=self._on_stop,
            state=tk.DISABLED,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.confirm_btn = _button(
            actions,
            text="Загрузить",
            command=lambda: self._on_confirm("receipts"),
            state=tk.DISABLED,
        )
        self.confirm_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.done_btn = _button(
            actions,
            text="Готово (логин)",
            command=self._on_done_login,
            state=tk.DISABLED,
        )
        self.done_btn.pack(side=tk.LEFT, padx=(8, 0))

        _button(
            actions,
            text="Загрузки",
            command=self._open_screens_folder,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.status_var = tk.StringVar(value="Готов к запуску")
        _label(
            root,
            textvariable=self.status_var,
            font=UI_FONT_SMALL,
            padx=10,
        ).pack(anchor=tk.W, pady=(4, 0))

        log_frame = _labelframe(root, text="Лог", padx=8, pady=8)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        self.log = scrolledtext.ScrolledText(
            log_frame,
            height=14,
            state=tk.DISABLED,
            font=UI_FONT_LOG,
            wrap=tk.WORD,
            bg=UI_LOG_BG,
            fg=UI_FG,
            insertbackground=UI_FG,
            relief=tk.FLAT,
            bd=1,
            highlightthickness=1,
            highlightbackground=UI_BORDER,
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.update_idletasks()
        self._poll_log()
        self._poll_confirm()
        self._append_log(
            "Готово. «Логин PlatCore» — войти в аккаунт.\n"
            "«Старт цикла» — Accept + Bank + скрины.\n"
        )

    def _parse_amount(self, raw: str) -> float | None:
        text = raw.strip().replace(",", ".")
        if not text:
            return None
        return float(text)

    def _save_settings(self, *, silent: bool = False) -> bool:
        try:
            max_deals = int(self.max_deals_var.get())
            empty_passes = int(self.empty_passes_var.get())
            min_amt = self._parse_amount(self.min_amount_var.get())
            max_amt = self._parse_amount(self.max_amount_var.get())
            allow_visa = bool(self.allow_visa_var.get())
            allow_mc = bool(self.allow_mc_var.get())
            apply_gui_settings(
                max_deals=max_deals,
                min_amount=min_amt,
                max_amount=max_amt,
                allow_visa=allow_visa,
                allow_mastercard=allow_mc,
                max_empty_list_passes=empty_passes,
            )
            if not silent:
                brands = []
                if allow_visa:
                    brands.append("Visa")
                if allow_mc:
                    brands.append("MC")
                self._append_log(
                    f"[OK] Сохранено: {max_deals} сделок, "
                    f"пустых кругов ≤ {empty_passes}"
                    + (
                        f", сумма {min_amt or '—'}–{max_amt or '—'}"
                        if min_amt is not None or max_amt is not None
                        else ""
                    )
                    + f", карты: {', '.join(brands) if brands else 'нет'}"
                    + "\n"
                )
            return True
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Настройки", f"Некорректное значение: {exc}")
            return False

    def _set_idle_ui(self) -> None:
        self.start_btn.configure(state=tk.NORMAL)
        self.login_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self.confirm_btn.configure(state=tk.DISABLED)
        self.done_btn.configure(state=tk.DISABLED)
        self.max_deals_spin.configure(state=tk.NORMAL)
        self.empty_passes_spin.configure(state=tk.NORMAL)
        self.save_btn.configure(state=tk.NORMAL)

    def _set_running_ui(self, mode: JobMode) -> None:
        self.start_btn.configure(state=tk.DISABLED)
        self.login_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.max_deals_spin.configure(state=tk.DISABLED)
        self.empty_passes_spin.configure(state=tk.DISABLED)
        self.save_btn.configure(state=tk.DISABLED)
        self.confirm_btn.configure(state=tk.DISABLED)
        self.done_btn.configure(state=tk.DISABLED)
        if mode == "login":
            self.done_btn.configure(state=tk.NORMAL)

    def _append_log(self, text: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _poll_log(self) -> None:
        while True:
            try:
                chunk = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(chunk)
        self.root.after(80, self._poll_log)

    def _set_running(self, running: bool, mode: JobMode = "") -> None:
        self._running = running
        self._job_mode = mode if running else ""
        if running:
            self._set_running_ui(mode)
        else:
            self._set_idle_ui()
            self.status_var.set("Готов к запуску")

    def _poll_confirm(self) -> None:
        try:
            prompt, done = self._confirm_requests.get_nowait()
            self._pending_confirm_done = done
            self._confirm_kind = "receipts"
            self.status_var.set(prompt)
            self._append_log(f"\n>>> {prompt}\n")
            if self._job_mode == "pipeline":
                self.confirm_btn.configure(state=tk.NORMAL)
            elif self._job_mode == "login":
                self.done_btn.configure(state=tk.NORMAL)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_confirm)

    def _open_screens_folder(self) -> None:
        import subprocess

        subprocess.run(["open", str(self._screens_dir)], check=False)

    def _signal_confirm(self) -> None:
        if self._pending_confirm_done is not None:
            self._pending_confirm_done.set()
            self._pending_confirm_done = None

    def _on_confirm(self, kind: str = "receipts") -> None:
        self.confirm_btn.configure(state=tk.DISABLED)
        self._confirm_kind = kind
        self.status_var.set("Обрабатываю…")
        self._signal_confirm()

    def _on_done_login(self) -> None:
        self.done_btn.configure(state=tk.DISABLED)
        self._confirm_kind = "receipts"
        self.status_var.set("Сохраняю сессию…")
        self._signal_confirm()

    def _on_stop(self) -> None:
        if not self._running:
            return
        request_stop()
        self._signal_confirm()
        self.status_var.set("Останавливаю…")
        self._append_log("\n[INFO] Запрошена остановка…\n")
        loop = self._worker_loop
        task = self._worker_task
        if loop is not None and task is not None and not task.done():
            loop.call_soon_threadsafe(task.cancel)

    async def _gui_confirm(self, prompt: str) -> str:
        done = threading.Event()
        self._confirm_kind = "receipts"
        self._confirm_requests.put((prompt.replace("\n", " ").strip(), done))
        await asyncio.to_thread(done.wait)
        return self._confirm_kind or "receipts"

    def _run_job_thread(self, coro_factory: Callable[[], object], mode: JobMode) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._worker_loop = loop
        set_confirm_handler(self._gui_confirm)
        begin_job()

        stdout_prev = sys.stdout
        stderr_prev = sys.stderr
        redirector = LogRedirector(self._log_queue)
        sys.stdout = redirector
        sys.stderr = redirector

        task = loop.create_task(coro_factory())  # type: ignore[arg-type]
        self._worker_task = task

        try:
            loop.run_until_complete(task)
            if not task.cancelled():
                self._log_queue.put("\n[OK] Завершено.\n")
        except asyncio.CancelledError:
            self._log_queue.put("\n[INFO] Остановлено.\n")
        except Exception:
            self._log_queue.put("\n[ERROR]\n" + traceback.format_exc())
        finally:
            set_confirm_handler(None)
            sys.stdout = stdout_prev
            sys.stderr = stderr_prev
            self._worker_loop = None
            self._worker_task = None
            loop.close()
            self.root.after(0, lambda: self._set_running(False))

    def _on_login(self) -> None:
        if self._running:
            return
        self._set_running(True, mode="login")
        self.status_var.set("Логин: войдите в браузере…")
        self._append_log("\n--- Логин PlatCore ---\n")
        self._worker = threading.Thread(
            target=lambda: self._run_job_thread(run_login, "login"),
            name="tzk-login",
            daemon=True,
        )
        self._worker.start()

    def _on_start(self) -> None:
        if self._running:
            return
        if not self._save_settings(silent=True):
            return
        max_deals = int(self.max_deals_var.get())
        if not messagebox.askyesno(
            "Старт",
            f"Запустить цикл ({max_deals} сделок)?\n\n"
            "PlatCore Accept → Bank → ожидание скринов.",
        ):
            return
        self._set_running(True, mode="pipeline")
        self.status_var.set("Фаза 1: Accept + Bank…")
        self._append_log(f"\n--- Старт цикла ({max_deals} сделок) ---\n")
        self._worker = threading.Thread(
            target=lambda: self._run_job_thread(run_pipeline, "pipeline"),
            name="tzk-pipeline",
            daemon=True,
        )
        self._worker.start()

    def _on_close(self) -> None:
        if self._running:
            if not messagebox.askyesno(
                "Выход",
                "Задача ещё выполняется. Остановить и выйти?",
            ):
                return
            self._on_stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        TzkApp(root)
    except Exception as exc:
        messagebox.showerror("Tzk — ошибка", f"{exc}\n\n{traceback.format_exc()}")
        root.destroy()
        raise
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
