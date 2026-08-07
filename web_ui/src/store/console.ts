import { create } from "zustand";
import {
  IDLE_STATUS,
  type CancelAlert,
  type DealRow,
  type DialogState,
  type LogEvent,
  type ProgressPanel,
  type RecoveryState,
  type StatusKind,
} from "@/lib/types";
import { clearTitleAttention, grabWindowAttention } from "@/lib/attention";

function emptyProgress(title: string): ProgressPanel {
  return {
    visible: false,
    processing: false,
    done: false,
    title,
    summary: "",
    message: "",
    deals: [],
  };
}

function formatAmountTjs(raw: unknown): string {
  const s = String(raw ?? "").trim();
  if (!s || s === "0" || s === "0.0") return "";
  if (/tjs/i.test(s)) return s.replace(/\s+/g, " ").trim();
  return `${s} TJS`;
}

function asDeals(raw: unknown): DealRow[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((d, i) => {
    const row = (d || {}) as Record<string, unknown>;
    const state = String(row.state || "");
    const amountTjs = formatAmountTjs(
      row.amount_tjs || row.amount_target || row.amount || "",
    );
    return {
      id: String(row.order_id || row.id || i),
      index: (row.index as string | number | undefined) ?? i + 1,
      holder: String(row.holder || row.name || ""),
      amount: amountTjs,
      card: String(row.card || row.card_short || ""),
      status: String(row.status || state || ""),
      state,
      error: row.error ? String(row.error) : undefined,
      active: !!row.active,
      order_id: row.order_id ? String(row.order_id) : undefined,
      has_shot: !!(row.has_shot || row.shot),
      has_video: !!(row.has_video || row.video),
      needs_video: !!row.needs_video,
      preview_ready: !!(row.preview_ready || row.ready),
      preview_hint: row.preview_hint
        ? String(row.preview_hint)
        : row.hint
          ? String(row.hint)
          : undefined,
      file_name: row.file_name ? String(row.file_name) : undefined,
      can_cancel: !!row.can_cancel,
      can_retry: !!row.can_retry,
      can_rescan: !!row.can_rescan,
    };
  });
}

function mergeReceiptPreview(
  deals: DealRow[],
  preview: Record<string, unknown> | null | undefined,
): DealRow[] {
  if (!preview || !Array.isArray(preview.deals) || !preview.deals.length) {
    return deals;
  }
  const byOrder = new Map<string, Record<string, unknown>>();
  for (const p of preview.deals) {
    const row = (p || {}) as Record<string, unknown>;
    const oid = row.order_id ? String(row.order_id) : "";
    if (oid) byOrder.set(oid, row);
  }
  return deals.map((d) => {
    const p = d.order_id ? byOrder.get(d.order_id) : undefined;
    if (!p) return d;
    const state = d.state || "";
    if (state === "pending" || state === "matched") {
      return {
        ...d,
        has_shot: !!p.has_shot,
        has_video: !!p.has_video,
        preview_ready: !!p.ready,
        preview_hint: p.hint ? String(p.hint) : "",
        file_name: p.file_name ? String(p.file_name) : "",
        needs_video: p.needs_video != null ? !!p.needs_video : d.needs_video,
        can_rescan: p.can_rescan ? true : d.can_rescan,
      };
    }
    if (state === "skipped" || state === "cancelled") {
      return {
        ...d,
        has_shot: false,
        has_video: false,
        preview_ready: false,
        preview_hint: state === "skipped" ? "пропуск банка — Отмена" : "",
        file_name: "",
      };
    }
    if (state === "error" && p.can_rescan) {
      return { ...d, can_rescan: true };
    }
    return d;
  });
}

type Settings = {
  maxDeals: number;
  emptyPasses: number;
  minAmount: string;
  maxAmount: string;
  allowVisa: boolean;
  allowMastercard: boolean;
  fromPending: boolean;
  redirMax: string;
  redirMin: string;
  redirMaxAmt: string;
  redirSkipBog: boolean;
  redirVisaOnly: boolean;
  redirAccounts: Record<string, boolean>;
  declineBank: "tbc" | "bog";
};

type ConsoleState = {
  view: "run" | "deals" | "log";
  statusText: string;
  statusKind: StatusKind;
  statusLabel: string;
  running: boolean;
  jobMode: string;
  waitingConfirm: boolean;
  confirmMode: string;
  appVersion: string;
  mediaDir: string;
  adbText: string;
  adbOk: boolean;
  settings: Settings;
  pipeline: ProgressPanel;
  receipts: ProgressPanel;
  decline: ProgressPanel;
  cancels: CancelAlert[];
  recovery: RecoveryState;
  logs: LogEvent[];
  dialog: DialogState;
  setView: (v: ConsoleState["view"]) => void;
  setStatus: (text: string, kind?: StatusKind | string) => void;
  setRunning: (running: boolean, jobMode?: string) => void;
  patchSettings: (p: Partial<Settings>) => void;
  applyState: (state: Record<string, unknown>) => void;
  appendLog: (text: string) => void;
  ingestLogEvents: (events: unknown[]) => void;
  clearLogs: () => void;
  updatePipelineProgress: (payload: Record<string, unknown>) => void;
  clearPipelineProgress: () => void;
  updateReceiptProgress: (payload: Record<string, unknown>) => void;
  clearReceiptProgress: () => void;
  applyReceiptPreview: (preview: Record<string, unknown>) => void;
  updateDeclineResult: (payload: Record<string, unknown>) => void;
  clearDeclineResult: () => void;
  appendCancelAlert: (payload: Record<string, unknown>) => void;
  clearCancelAlerts: () => void;
  setConfirmPrompt: (prompt: string, mode: string) => void;
  setRecoveryPrompt: (
    message: string,
    detail: string,
    hint: string,
    summary: Record<string, unknown>,
    allowRetry: boolean,
  ) => void;
  hideRecoveryPrompt: () => void;
  openDialog: (opts: Omit<DialogState, "open" | "resolve">) => Promise<boolean>;
  closeDialog: (ok: boolean) => void;
};

let logSeq = 0;

const LABELS: Record<StatusKind, string> = {
  idle: "Готов",
  running: "Работает",
  waiting: "Ждёт вас",
  success: "Готово",
  error: "Ошибка",
};

export const useConsole = create<ConsoleState>((set, get) => ({
  view: "run",
  statusText: IDLE_STATUS,
  statusKind: "idle",
  statusLabel: LABELS.idle,
  running: false,
  jobMode: "",
  waitingConfirm: false,
  confirmMode: "",
  appVersion: "?",
  mediaDir: "Папка загрузок",
  adbText: "Не проверен",
  adbOk: false,
  settings: {
    maxDeals: 5,
    emptyPasses: 2,
    minAmount: "",
    maxAmount: "",
    allowVisa: true,
    allowMastercard: false,
    fromPending: false,
    redirMax: "5",
    redirMin: "",
    redirMaxAmt: "",
    redirSkipBog: false,
    redirVisaOnly: false,
    redirAccounts: {
      "redir-104-1": true,
      "redir-104-2": true,
      "redir-104-3": true,
    },
    declineBank: "tbc",
  },
  pipeline: emptyProgress("Ход работы"),
  receipts: emptyProgress("Чеки"),
  decline: emptyProgress("Результат"),
  cancels: [],
  recovery: {
    open: false,
    message: "",
    detail: "",
    hint: "",
    allowRetry: false,
    continueLabel: "Пропустить сделку",
    deal: null,
  },
  logs: [],
  dialog: { open: false, title: "", body: "" },

  setView: (view) => set({ view }),

  setStatus: (text, kind) => {
    const k = (["idle", "running", "waiting", "success", "error"].includes(
      String(kind),
    )
      ? kind
      : "idle") as StatusKind;
    set({
      statusText: text || IDLE_STATUS,
      statusKind: k,
      statusLabel: LABELS[k],
    });
  },

  setRunning: (running, jobMode = "") =>
    set({
      running,
      jobMode: jobMode || "",
      waitingConfirm: running ? get().waitingConfirm : false,
    }),

  patchSettings: (p) => set({ settings: { ...get().settings, ...p } }),

  applyState: (state) => {
    const s = get().settings;
    const has = (key: string) =>
      Object.prototype.hasOwnProperty.call(state, key);

    const nextSettings: Settings = {
      ...s,
      maxDeals: has("max_deals")
        ? Number(state.max_deals) || s.maxDeals || 5
        : s.maxDeals,
      emptyPasses: has("max_empty_list_passes")
        ? Number(state.max_empty_list_passes) || s.emptyPasses
        : s.emptyPasses,
      minAmount: has("min_amount")
        ? String(state.min_amount ?? "")
        : s.minAmount,
      maxAmount: has("max_amount")
        ? String(state.max_amount ?? "")
        : s.maxAmount,
      // partial applyState (check_adb) раньше сбрасывал MC в false
      allowVisa: has("allow_visa") ? state.allow_visa !== false : s.allowVisa,
      allowMastercard: has("allow_mastercard")
        ? !!state.allow_mastercard
        : s.allowMastercard,
      fromPending: has("from_pending") ? !!state.from_pending : s.fromPending,
      redirSkipBog: has("redirect_skip_bog")
        ? !!state.redirect_skip_bog
        : s.redirSkipBog,
      redirVisaOnly: has("redirect_visa_only")
        ? !!state.redirect_visa_only
        : s.redirVisaOnly,
    };
    if (state.video_min_usdt != null && state.video_min_usdt !== "") {
      window.__videoMinUsdt = Number(state.video_min_usdt);
    }

    const patch: Partial<ConsoleState> = { settings: nextSettings };

    if (has("videos_dir") || has("screens_dir")) {
      patch.mediaDir = String(
        state.videos_dir || state.screens_dir || get().mediaDir || "Папка загрузок",
      );
    }
    if (has("adb_device")) {
      patch.adbText = String(state.adb_device || "не подключён");
    }
    if (has("adb_ok")) {
      patch.adbOk = !!state.adb_ok;
    }
    if (has("app_version") && state.app_version) {
      patch.appVersion = String(state.app_version);
    }

    // Полный get_state — обновляем running/status; частичный (только ADB) — нет
    if (has("running") || has("status") || has("job_mode")) {
      const status = String(state.status || get().statusText || IDLE_STATUS);
      const running = has("running") ? !!state.running : get().running;
      const jobMode = has("job_mode")
        ? String(state.job_mode || "")
        : get().jobMode;
      let kind: StatusKind = "idle";
      if (running) kind = state.confirm_enabled ? "waiting" : "running";
      else if (
        status.startsWith("Готов") ||
        status === IDLE_STATUS ||
        status === "Продолжаю обработку…"
      )
        kind = "idle";
      else kind = get().statusKind === "error" ? "error" : "success";

      patch.running = running;
      patch.jobMode = jobMode;
      patch.waitingConfirm = !!state.confirm_enabled;
      patch.confirmMode = state.confirm_enabled ? jobMode : "";
      patch.statusText =
        kind === "idle" && (status.startsWith("Готов") || status === IDLE_STATUS)
          ? IDLE_STATUS
          : status;
      patch.statusKind = kind;
      patch.statusLabel = LABELS[kind];
      patch.recovery = state.recovery_enabled
        ? { ...get().recovery, open: true }
        : { ...get().recovery, open: false };
    }

    set(patch);
  },

  appendLog: (text) => {
    const lines = String(text || "")
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (!lines.length) return;
    const add: LogEvent[] = lines.map((message) => ({
      id: ++logSeq,
      time: new Date().toLocaleTimeString("ru-RU", { hour12: false }),
      level: "info",
      service: "gui",
      message,
      status: "ok",
    }));
    set({ logs: [...add, ...get().logs].slice(0, 500) });
  },

  ingestLogEvents: (events) => {
    if (!Array.isArray(events) || !events.length) return;
    const add: LogEvent[] = events.map((raw) => {
      const e = (raw || {}) as Record<string, unknown>;
      return {
        id: ++logSeq,
        time: String(e.time || e.ts || ""),
        level: String(e.level || "info"),
        service: String(e.service || e.source || ""),
        message: String(e.message || e.msg || e.text || ""),
        status: String(e.status || ""),
        tags: Array.isArray(e.tags) ? e.tags.map(String) : [],
        raw: e,
      };
    });
    set({ logs: [...add.reverse(), ...get().logs].slice(0, 500) });
  },

  clearLogs: () => set({ logs: [] }),

  updatePipelineProgress: (payload) => {
    const phase = String(payload.phase || "");
    const deals = asDeals(payload.deals);
    const paid = Number(payload.paid || 0);
    const total = Number(payload.total || deals.length || 0);
    const skipped = Number(payload.skipped || 0);
    const processing = phase !== "done";
    let title = "Ход работы";
    if (phase === "searching") title = "Поиск сделок";
    else if (phase === "done") title = "Обработка закончена";
    else title = "Обработка сделок";

    set({
      pipeline: {
        visible: true,
        processing,
        done: phase === "done",
        title: String(payload.title || title),
        summary:
          String(payload.summary || "") ||
          (total ? `${paid} из ${total}${skipped ? `, пропуск ${skipped}` : ""}` : ""),
        message: String(payload.message || ""),
        deals,
        success: payload.success_text ? String(payload.success_text) : undefined,
        hasErrors: !!payload.has_errors || skipped > 0,
        // indeterminate while running
        progress: phase === "done" ? 1 : undefined,
        phase,
      },
    });
  },

  clearPipelineProgress: () => set({ pipeline: emptyProgress("Ход работы") }),

  updateReceiptProgress: (payload) => {
    const phase = String(payload.phase || "waiting");
    const deals = asDeals(payload.deals);
    const done = Number(payload.done || 0);
    const failed = Number(payload.failed || 0);
    const total = Number(payload.total || deals.length || 0);
    const message = String(payload.message || "");

    let title = "Ожидание загрузки чеков";
    if (phase === "processing") title = "Обработка чеков";
    else if (phase === "done")
      title = failed > 0 ? "Готово с ошибками" : "Чеки загружены";
    else if (phase === "error") title = "Ошибка загрузки чеков";

    const summary =
      phase === "waiting"
        ? `0 из ${total} готовы`
        : `${done} из ${total}`;

    const progress =
      phase === "waiting"
        ? 0
        : total > 0
          ? done / total
          : phase === "done"
            ? 1
            : undefined;

    set({
      // Как в legacy: сделки уходят из «Обработка» в «Чеки»
      pipeline: emptyProgress("Ход работы"),
      receipts: {
        visible: true,
        processing: phase === "processing" || phase === "waiting",
        done: phase === "done",
        title: String(payload.title || title),
        summary: String(payload.summary || summary),
        message,
        deals,
        success:
          phase === "done"
            ? String(payload.success_text || message || `Загружено ${done} из ${total}`)
            : undefined,
        errorDetail: payload.error_detail
          ? String(payload.error_detail)
          : undefined,
        hasErrors: phase === "error" || failed > 0,
        progress,
        phase,
        allowCancel: !!payload.allow_cancel,
      },
    });
  },

  clearReceiptProgress: () => set({ receipts: emptyProgress("Чеки") }),

  applyReceiptPreview: (preview) => {
    if (!preview || preview.ok === false) return;
    const cur = get().receipts;
    if (!cur.visible || (cur.phase && cur.phase !== "waiting")) return;

    const deals = mergeReceiptPreview(cur.deals, preview);
    const awaiting = deals.filter(
      (d) => d.state === "pending" || d.state === "matched",
    ).length;
    const skipped = deals.filter((d) => d.state === "skipped").length;
    const ready = Number(preview.ready_count || 0);
    const total = Number(preview.total || cur.deals.length || 0);

    let summary: string;
    if (!awaiting && skipped > 0) {
      summary = `пропуск — Отмена (${skipped})`;
    } else {
      summary = `${ready} из ${total || awaiting} готовы`;
    }

    set({
      receipts: {
        ...cur,
        deals,
        summary,
        progress: total ? ready / total : 0,
        processing: true,
        done: false,
      },
    });
  },

  updateDeclineResult: (payload) => {
    const isRedirect = String(payload.action || "cancel") === "redirect";
    const doneCount = Number(
      isRedirect ? payload.redirected || 0 : payload.cancelled || 0,
    );
    const failed = Number(payload.failed || 0);
    const total = Number(payload.total || (payload.deals as unknown[])?.length || 0);
    const message =
      String(payload.message || "") ||
      (isRedirect
        ? `Передано ${doneCount} из ${total}`
        : `Отменено ${doneCount} из ${total}`);
    const hasErrors = failed > 0 || (doneCount === 0 && total > 0);

    set({
      decline: {
        visible: true,
        processing: false,
        done: true,
        title: String(
          payload.title ||
            (hasErrors
              ? isRedirect
                ? "Передано с ошибками"
                : "Снято с ошибками"
              : isRedirect
                ? "Сделки переданы"
                : "Сделки сняты"),
        ),
        summary:
          total === 0 ? "0" : `${doneCount} из ${total}${failed ? `, ошибок ${failed}` : ""}`,
        message,
        deals: asDeals(payload.deals),
        success: payload.success_text ? String(payload.success_text) : undefined,
        hasErrors,
      },
    });

    void get().openDialog({
      title: hasErrors ? "Не успешно" : "Успешно",
      body: message,
      danger: hasErrors,
      alert: true,
    });
  },

  clearDeclineResult: () => set({ decline: emptyProgress("Результат") }),

  appendCancelAlert: (payload) => {
    const item: CancelAlert = {
      id: `${Date.now()}-${Math.random()}`,
      amount: payload.amount ? String(payload.amount) : undefined,
      ts: payload.ts ? String(payload.ts) : undefined,
      card: payload.card ? String(payload.card) : undefined,
      balance: payload.balance ? String(payload.balance) : undefined,
      match_label: payload.match_label ? String(payload.match_label) : undefined,
      match_holder: payload.match_holder ? String(payload.match_holder) : undefined,
      match_index: payload.match_index as string | number | undefined,
      match_card: payload.match_card ? String(payload.match_card) : undefined,
      match_amount_tjs: payload.match_amount_tjs as string | number | undefined,
      raw: payload.raw ? String(payload.raw) : undefined,
    };
    set({ cancels: [item, ...get().cancels].slice(0, 20) });
    const who = item.match_holder || item.match_label || item.card || "";
    get().setStatus("Отмена списания" + (who ? `: ${who}` : ""), "error");
    get().appendLog(`[ALERT] Отмена списания ${item.amount || ""} ${item.card || ""}`);
  },

  clearCancelAlerts: () => set({ cancels: [] }),

  setConfirmPrompt: (prompt, mode) => {
    set({
      waitingConfirm: true,
      confirmMode: mode,
      statusText: prompt,
      statusKind: "waiting",
      statusLabel: LABELS.waiting,
    });
    get().appendLog(`>>> ${prompt}`);
  },

  setRecoveryPrompt: (message, detail, hint, summary, allowRetry) => {
    const hasDeal = !!(summary?.index || summary?.card || summary?.holder);
    set({
      recovery: {
        open: true,
        message: message || "Произошла ошибка",
        detail: detail || "Неизвестная ошибка",
        hint: hint || "",
        allowRetry: !!allowRetry,
        continueLabel: summary?.payment_done
          ? String(summary.continue_label || "Продолжить")
          : "Пропустить сделку",
        deal: hasDeal
          ? {
              index: summary.index ? `#${summary.index}` : "—",
              card: String(summary.card || summary.card_short || "—"),
              holder: String(summary.holder || "—"),
              amount_tjs: String(summary.amount_tjs || "—"),
              amount_target: String(summary.amount_target || "—"),
            }
          : null,
      },
      statusText: message || "Ошибка",
      statusKind: "error",
      statusLabel: LABELS.error,
      waitingConfirm: false,
    });
    get().appendLog(`!!! ${message}\n${detail || ""}`);
    grabWindowAttention("⚠ " + (message || "Ошибка"), detail || "");
  },

  hideRecoveryPrompt: () => {
    clearTitleAttention();
    set({
      recovery: {
        ...get().recovery,
        open: false,
        continueLabel: "Пропустить сделку",
      },
    });
  },

  openDialog: (opts) =>
    new Promise<boolean>((resolve) => {
      set({
        dialog: {
          open: true,
          title: opts.title || "Подтверждение",
          body: opts.body || "",
          danger: opts.danger,
          alert: opts.alert,
          resolve,
        },
      });
    }),

  closeDialog: (ok) => {
    const d = get().dialog;
    d.resolve?.(ok);
    set({ dialog: { open: false, title: "", body: "", alert: false } });
  },
}));
