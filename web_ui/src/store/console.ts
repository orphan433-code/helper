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

function asDeals(raw: unknown): DealRow[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((d, i) => {
    const row = (d || {}) as Record<string, unknown>;
    return {
      id: String(row.order_id || row.id || i),
      index: (row.index as string | number | undefined) ?? i + 1,
      holder: String(row.holder || row.name || ""),
      amount: String(row.amount || row.amount_usdt || row.amount_tjs || ""),
      card: String(row.card || row.card_short || ""),
      status: String(row.status || row.state || ""),
      state: String(row.state || ""),
      error: row.error ? String(row.error) : undefined,
      active: !!row.active,
      order_id: row.order_id ? String(row.order_id) : undefined,
      has_shot: !!(row.has_shot || row.shot),
      has_video: !!(row.has_video || row.video),
    };
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
    const nextSettings: Settings = {
      ...s,
      maxDeals: Number(state.max_deals ?? s.maxDeals) || 5,
      emptyPasses:
        state.max_empty_list_passes != null
          ? Number(state.max_empty_list_passes)
          : s.emptyPasses,
      minAmount: String(state.min_amount ?? s.minAmount ?? ""),
      maxAmount: String(state.max_amount ?? s.maxAmount ?? ""),
      allowVisa: state.allow_visa !== false,
      allowMastercard: !!state.allow_mastercard,
      fromPending: !!state.from_pending,
      redirSkipBog: !!state.redirect_skip_bog,
      redirVisaOnly: !!state.redirect_visa_only,
    };
    if (state.video_min_usdt != null && state.video_min_usdt !== "") {
      window.__videoMinUsdt = Number(state.video_min_usdt);
    }
    const status = String(state.status || IDLE_STATUS);
    const running = !!state.running;
    const jobMode = String(state.job_mode || "");
    let kind: StatusKind = "idle";
    if (running) kind = state.confirm_enabled ? "waiting" : "running";
    else if (
      status.startsWith("Готов") ||
      status === IDLE_STATUS ||
      status === "Продолжаю обработку…"
    )
      kind = "idle";
    else kind = "success";

    set({
      settings: nextSettings,
      mediaDir: String(
        state.videos_dir || state.screens_dir || get().mediaDir || "Папка загрузок",
      ),
      adbText: String(state.adb_device || "не подключён"),
      adbOk: !!state.adb_ok,
      appVersion: state.app_version ? String(state.app_version) : get().appVersion,
      running,
      jobMode,
      waitingConfirm: !!state.confirm_enabled,
      confirmMode: state.confirm_enabled ? jobMode : "",
      statusText:
        kind === "idle" && (status.startsWith("Готов") || status === IDLE_STATUS)
          ? IDLE_STATUS
          : status,
      statusKind: kind,
      statusLabel: LABELS[kind],
      recovery: state.recovery_enabled
        ? { ...get().recovery, open: true }
        : { ...get().recovery, open: false },
    });
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
    set({
      pipeline: {
        visible: true,
        processing: phase !== "done",
        done: phase === "done",
        title: String(payload.title || "Ход работы"),
        summary: String(payload.summary || ""),
        message: String(payload.message || ""),
        deals: asDeals(payload.deals),
        success: payload.success_text ? String(payload.success_text) : undefined,
        hasErrors: !!payload.has_errors || Number(payload.skipped || 0) > 0,
      },
    });
  },

  clearPipelineProgress: () => set({ pipeline: emptyProgress("Ход работы") }),

  updateReceiptProgress: (payload) => {
    const phase = String(payload.phase || "");
    set({
      receipts: {
        visible: true,
        processing: phase !== "done" && phase !== "error",
        done: phase === "done",
        title: String(payload.title || "Чеки"),
        summary: String(payload.summary || ""),
        message: String(payload.message || ""),
        deals: asDeals(payload.deals),
        success: payload.success_text ? String(payload.success_text) : undefined,
        errorDetail: payload.error_detail ? String(payload.error_detail) : undefined,
        hasErrors: phase === "error",
      },
    });
  },

  clearReceiptProgress: () => set({ receipts: emptyProgress("Чеки") }),

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
