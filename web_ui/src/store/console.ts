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
import {
  allCatalogBins,
  DEFAULT_DECLINE_BINS,
  EXTRA_REDIRECT_BINS,
} from "@/lib/bankBins";

const CATALOG_BINS = allCatalogBins();
const REDIRECT_FALLBACK_LIST = [
  ...CATALOG_BINS,
  ...EXTRA_REDIRECT_BINS.filter((b) => !CATALOG_BINS.includes(b)),
];
const DECLINE_FALLBACK_TOGGLES = Object.fromEntries(
  CATALOG_BINS.map((p) => [p, DEFAULT_DECLINE_BINS.includes(p)]),
);
const REDIRECT_FALLBACK_TOGGLES = Object.fromEntries(
  REDIRECT_FALLBACK_LIST.map((p) => [p, false]),
);

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

/** Панель «идёт работа» для редиректа / снятия — пока бэкенд не прислал итог. */
function busyDeclinePanel(jobMode: string): ProgressPanel {
  const isRedirect = jobMode === "redirect";
  const isAccept = jobMode === "accept_names";
  return {
    visible: true,
    processing: true,
    done: false,
    title: isRedirect ? "Редирект" : isAccept ? "Принятие" : "Отмена",
    summary: "…",
    message: isRedirect ? "Передаю…" : isAccept ? "Принимаю…" : "Отменяю…",
    deals: [],
    progress: undefined,
    phase: "processing",
  };
}

function formatAmountTjs(raw: unknown): string {
  const s = String(raw ?? "").trim();
  if (!s || s === "0" || s === "0.0") return "";
  if (/tjs/i.test(s)) return s.replace(/\s+/g, " ").trim();
  return `${s} TJS`;
}

function readOrderId(row: Record<string, unknown>): string | undefined {
  const raw = row.order_id ?? row.orderId ?? row.deal_id ?? row.dealId;
  const s = String(raw ?? "").trim();
  return s || undefined;
}

function asDeals(raw: unknown): DealRow[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((d, i) => {
    const row = (d || {}) as Record<string, unknown>;
    const state = String(row.state || "");
    const order_id = readOrderId(row);
    const amountTjs = formatAmountTjs(
      row.amount_tjs || row.amount_target || row.amount || "",
    );
    return {
      id: order_id || String(row.id || i),
      index: (row.index as string | number | undefined) ?? i + 1,
      holder: String(row.holder || row.name || ""),
      amount: amountTjs,
      card: String(row.card || row.card_short || ""),
      status: String(row.status || state || ""),
      state,
      error: row.error ? String(row.error) : undefined,
      ok: row.ok !== false && !row.error,
      active: !!row.active,
      order_id,
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

function isAwaitingReceipt(deal: DealRow): boolean {
  const state = deal.state || "";
  return state === "pending" || state === "matched";
}

function countAwaitingReceiptDeals(deals: DealRow[]): number {
  return deals.filter(isAwaitingReceipt).length;
}

function countReceiptReady(deals: DealRow[]): number {
  return deals.filter((d) => {
    if (d.state === "done" || d.state === "cancelled") return true;
    if (d.preview_ready) return true;
    if (isAwaitingReceipt(d) && d.has_shot && (!d.needs_video || d.has_video)) {
      return true;
    }
    return false;
  }).length;
}

function preserveReceiptPreviewFields(prev: DealRow[], next: DealRow[]): DealRow[] {
  const byOrder = new Map(
    prev.filter((d) => d.order_id).map((d) => [d.order_id!, d]),
  );
  return next.map((d) => {
    const p = d.order_id ? byOrder.get(d.order_id) : undefined;
    if (!p || !isAwaitingReceipt(d)) return d;
    if (!p.has_shot && !p.preview_hint && !p.file_name && !p.preview_ready) return d;
    return {
      ...d,
      has_shot: p.has_shot || d.has_shot,
      has_video: p.has_video || d.has_video,
      preview_ready: p.preview_ready || d.preview_ready,
      preview_hint: p.preview_hint || d.preview_hint,
      file_name: p.file_name || d.file_name,
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
  const byIndex = new Map<string, Record<string, unknown>>();
  for (const p of preview.deals) {
    const row = (p || {}) as Record<string, unknown>;
    const oid = row.order_id ? String(row.order_id) : "";
    if (oid) byOrder.set(oid, row);
    if (row.index != null && row.index !== "") {
      byIndex.set(String(row.index), row);
    }
  }
  return deals.map((d) => {
    const p =
      (d.order_id ? byOrder.get(d.order_id) : undefined) ||
      (d.index != null ? byIndex.get(String(d.index)) : undefined);
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

function receiptWaitingSummary(
  deals: DealRow[],
  total: number,
  readyHint: number | null,
): string {
  const awaiting = countAwaitingReceiptDeals(deals);
  const skipped = deals.filter((d) => d.state === "skipped").length;
  if (!awaiting && skipped > 0) {
    return `пропуск — Отмена (${skipped})`;
  }
  const ready = readyHint != null ? readyHint : countReceiptReady(deals);
  return `${ready} из ${total || awaiting || deals.length} готовы`;
}

type Settings = {
  maxDeals: number;
  emptyPasses: number;
  minAmount: string;
  maxAmount: string;
  allowVisa: boolean;
  allowMastercard: boolean;
  fromPending: boolean;
  pipelineBinList: string[];
  pipelineBins: Record<string, boolean>;
  redirMax: string;
  redirMin: string;
  redirMaxAmt: string;
  redirSkipBog: boolean;
  redirVisaOnly: boolean;
  redirMaxRemaining: boolean;
  redirAccounts: Record<string, boolean>;
  redirectBinList: string[];
  redirectBins: Record<string, boolean>;
  declineBinList: string[];
  declineBins: Record<string, boolean>;
  declineTbc: boolean;
  declineMax: string;
  declineMinAmt: string;
  declineMaxAmt: string;
  acceptNamesMax: string;
  acceptNamesMinAmt: string;
  acceptNamesMaxAmt: string;
};

type ConsoleState = {
  view: "run" | "deals" | "agent" | "log";
  statusText: string;
  statusKind: StatusKind;
  statusLabel: string;
  running: boolean;
  jobMode: string;
  waitingConfirm: boolean;
  confirmMode: string;
  appVersion: string;
  agentConfigured: boolean;
  mediaDir: string;
  adbText: string;
  adbOk: boolean;
  settings: Settings;
  pipeline: ProgressPanel;
  receipts: ProgressPanel;
  lastReceiptPreview: Record<string, unknown> | null;
  decline: ProgressPanel;
  cancels: CancelAlert[];
  recovery: RecoveryState;
  logs: LogEvent[];
  dialog: DialogState;
  declineResultOpen: boolean;
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
  dismissDeclineResult: () => void;
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
  agentConfigured: false,
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
    pipelineBinList: ["537524", "557755"],
    pipelineBins: {
      "537524": false,
      "557755": false,
    },
    redirMax: "5",
    redirMin: "",
    redirMaxAmt: "",
    redirSkipBog: false,
    redirVisaOnly: false,
    redirMaxRemaining: false,
    redirAccounts: {
      "redir-104-1": true,
      "redir-104-2": true,
      "redir-104-3": true,
    },
    redirectBinList: REDIRECT_FALLBACK_LIST,
    redirectBins: { ...REDIRECT_FALLBACK_TOGGLES },
    declineBinList: [...CATALOG_BINS],
    declineBins: { ...DECLINE_FALLBACK_TOGGLES },
    declineTbc: true,
    declineMax: "10",
    declineMinAmt: "",
    declineMaxAmt: "",
    acceptNamesMax: "5",
    acceptNamesMinAmt: "",
    acceptNamesMaxAmt: "",
  },
  pipeline: emptyProgress("Ход работы"),
  receipts: emptyProgress("Чеки"),
  lastReceiptPreview: null,
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
  declineResultOpen: false,

  setView: (view) => set({ view }),

  setStatus: (text, kind) => {
    const raw = String(kind || "");
    const k = (
      ["idle", "running", "waiting", "success", "error"].includes(raw)
        ? raw
        : get().running
          ? "running"
          : "idle"
    ) as StatusKind;
    set({
      statusText: text || IDLE_STATUS,
      statusKind: k,
      statusLabel: LABELS[k],
    });
  },

  setRunning: (running, jobMode = "") => {
    const mode = jobMode || "";
    const patch: Partial<ConsoleState> = {
      running,
      jobMode: mode,
      waitingConfirm: running ? get().waitingConfirm : false,
    };
    if (running && (mode === "redirect" || mode === "decline" || mode === "accept_names")) {
      patch.decline = busyDeclinePanel(mode);
      patch.declineResultOpen = false;
      patch.statusKind = "running";
      patch.statusLabel = LABELS.running;
    }
    set(patch);
  },

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
      pipelineBinList:
        has("pipeline_bin_list") && Array.isArray(state.pipeline_bin_list)
          ? (state.pipeline_bin_list as string[]).map(String)
          : s.pipelineBinList,
      pipelineBins: (() => {
        const list =
          has("pipeline_bin_list") && Array.isArray(state.pipeline_bin_list)
            ? (state.pipeline_bin_list as string[]).map(String)
            : s.pipelineBinList;
        const raw =
          has("pipeline_bin_toggles") &&
          state.pipeline_bin_toggles &&
          typeof state.pipeline_bin_toggles === "object"
            ? (state.pipeline_bin_toggles as Record<string, boolean>)
            : s.pipelineBins;
        const next: Record<string, boolean> = {};
        for (const p of list) {
          next[p] = raw[p] === true;
        }
        return next;
      })(),
      redirSkipBog: has("redirect_skip_bog")
        ? !!state.redirect_skip_bog
        : s.redirSkipBog,
      redirVisaOnly: has("redirect_visa_only")
        ? !!state.redirect_visa_only
        : s.redirVisaOnly,
      redirMaxRemaining: has("redirect_max_remaining")
        ? !!state.redirect_max_remaining
        : s.redirMaxRemaining,
      redirectBinList:
        has("redirect_bin_list") && Array.isArray(state.redirect_bin_list)
          ? (state.redirect_bin_list as string[]).map(String)
          : s.redirectBinList,
      redirectBins: (() => {
        const list =
          has("redirect_bin_list") && Array.isArray(state.redirect_bin_list)
            ? (state.redirect_bin_list as string[]).map(String)
            : s.redirectBinList;
        const raw =
          has("redirect_bin_toggles") &&
          state.redirect_bin_toggles &&
          typeof state.redirect_bin_toggles === "object"
            ? (state.redirect_bin_toggles as Record<string, boolean>)
            : s.redirectBins;
        const next: Record<string, boolean> = {};
        for (const p of list) {
          next[p] = raw[p] === true;
        }
        return next;
      })(),
      redirMax: has("redirect_max_per_run")
        ? String(state.redirect_max_per_run ?? s.redirMax)
        : s.redirMax,
      redirMin: has("redirect_min_amount")
        ? String(state.redirect_min_amount ?? "")
        : s.redirMin,
      redirMaxAmt: has("redirect_max_amount")
        ? String(state.redirect_max_amount ?? "")
        : s.redirMaxAmt,
      declineBinList:
        has("decline_bin_list") && Array.isArray(state.decline_bin_list)
          ? (state.decline_bin_list as unknown[])
              .map((p) => String(p || "").replace(/\D/g, ""))
              .filter(Boolean)
          : s.declineBinList,
      declineBins: (() => {
        const list =
          has("decline_bin_list") && Array.isArray(state.decline_bin_list)
            ? (state.decline_bin_list as unknown[])
                .map((p) => String(p || "").replace(/\D/g, ""))
                .filter(Boolean)
            : s.declineBinList;
        const raw =
          has("decline_bin_toggles") &&
          state.decline_bin_toggles &&
          typeof state.decline_bin_toggles === "object"
            ? (state.decline_bin_toggles as Record<string, boolean>)
            : s.declineBins;
        const next: Record<string, boolean> = {};
        for (const p of list) {
          next[p] = p in raw ? raw[p] !== false : DEFAULT_DECLINE_BINS.includes(p);
        }
        return next;
      })(),
      declineTbc: has("decline_tbc") ? state.decline_tbc !== false : s.declineTbc,
      declineMax: has("decline_max_per_run")
        ? String(state.decline_max_per_run ?? s.declineMax)
        : s.declineMax,
      declineMinAmt: has("decline_min_amount")
        ? String(state.decline_min_amount ?? "")
        : s.declineMinAmt,
      declineMaxAmt: has("decline_max_amount")
        ? String(state.decline_max_amount ?? "")
        : s.declineMaxAmt,
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
    if (has("agent_configured")) {
      patch.agentConfigured = !!state.agent_configured;
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
      // После перезагрузки UI — если редирект/снятие ещё идут, показать busy-панель
      if (
        running &&
        (jobMode === "redirect" ||
          jobMode === "decline" ||
          jobMode === "accept_names") &&
        !get().decline.processing
      ) {
        patch.decline = busyDeclinePanel(jobMode);
      }
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
    const cur = get().receipts;
    const preview = phase === "waiting" ? get().lastReceiptPreview : null;
    let deals = asDeals(payload.deals);
    if (phase === "waiting") {
      if (preview) {
        deals = mergeReceiptPreview(deals, preview);
      } else if (cur.deals.length) {
        deals = preserveReceiptPreviewFields(cur.deals, deals);
      }
    }
    const done = Number(payload.done || 0);
    const failed = Number(payload.failed || 0);
    const total = Number(payload.total || deals.length || 0);
    const message = String(payload.message || "");

    let title = "Ожидание загрузки чеков";
    if (phase === "processing") title = "Обработка чеков";
    else if (phase === "done")
      title = failed > 0 ? "Готово с ошибками" : "Чеки загружены";
    else if (phase === "error") title = "Ошибка загрузки чеков";

    const readyHint =
      phase === "waiting" && preview && preview.ok !== false
        ? Number(preview.ready_count || 0)
        : null;
    const summary =
      phase === "waiting"
        ? receiptWaitingSummary(deals, total, readyHint)
        : `${done} из ${total}`;

    const readyForBar =
      phase === "waiting"
        ? readyHint != null
          ? readyHint
          : countReceiptReady(deals)
        : done;

    // processing + done=0 → undefined = indeterminate-полоска (видно, что идёт работа)
    const progress =
      phase === "waiting"
        ? total
          ? readyForBar / total
          : 0
        : phase === "done"
          ? 1
          : phase === "processing" && done === 0
            ? undefined
            : total > 0
              ? done / total
              : undefined;

    set({
      // Как в legacy: сделки уходят из «Обработка» в «Чеки»
      pipeline: emptyProgress("Ход работы"),
      lastReceiptPreview:
        phase === "processing" || phase === "done" ? null : get().lastReceiptPreview,
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

  clearReceiptProgress: () =>
    set({ receipts: emptyProgress("Чеки"), lastReceiptPreview: null }),

  applyReceiptPreview: (preview) => {
    if (!preview || preview.ok === false) return;
    const cur = get().receipts;
    if (!cur.visible || (cur.phase && cur.phase !== "waiting")) return;

    const deals = mergeReceiptPreview(cur.deals, preview);
    const ready = Number(preview.ready_count || 0);
    const total = Number(preview.total || cur.deals.length || 0);
    const summary = receiptWaitingSummary(deals, total, ready);
    const filesFound = Number(preview.files_found || 0);
    const unmatched = Array.isArray(preview.unmatched_files)
      ? preview.unmatched_files.length
      : 0;
    let message = cur.message;
    if (ready === 0 && filesFound > 0 && countAwaitingReceiptDeals(deals) > 0) {
      message =
        unmatched > 0
          ? `В папке ${filesFound} файл(ов), карта не совпала — проверь скрин`
          : `В папке ${filesFound} файл(ов), ждём совпадение по карте`;
    } else if (ready > 0) {
      message = `Найдено ${ready} из ${countAwaitingReceiptDeals(deals) || total}`;
    }

    set({
      lastReceiptPreview: preview,
      receipts: {
        ...cur,
        deals,
        summary,
        message,
        progress: total ? ready / total : 0,
        processing: true,
        done: false,
      },
    });
  },

  updateDeclineResult: (payload) => {
    const action = String(payload.action || "cancel");
    const isRedirect = action === "redirect";
    const isAccept = action === "accept";
    const doneCount = Number(
      isRedirect
        ? payload.redirected || 0
        : isAccept
          ? payload.accepted || 0
          : payload.cancelled || 0,
    );
    const failed = Number(payload.failed || 0);
    const total = Number(payload.total || (payload.deals as unknown[])?.length || 0);
    const message =
      String(payload.message || "") ||
      (isRedirect
        ? `Передано ${doneCount} из ${total}`
        : isAccept
          ? `Принято ${doneCount} из ${total}`
          : `Отменено ${doneCount} из ${total}`);
    const hasErrors = failed > 0 || (doneCount === 0 && total > 0);

    set({
      decline: {
        visible: true,
        processing: false,
        done: true,
        phase: "done",
        title: String(payload.title || (hasErrors ? "Ошибки" : "Готово")),
        summary:
          total === 0 ? "0" : `${doneCount} из ${total}${failed ? `, ошибок ${failed}` : ""}`,
        message,
        deals: asDeals(payload.deals),
        success: payload.success_text ? String(payload.success_text) : undefined,
        hasErrors,
        progress: total > 0 ? doneCount / total : doneCount > 0 ? 1 : 0,
      },
      declineResultOpen: true,
    });
  },

  clearDeclineResult: () => {
    const { running, jobMode } = get();
    // Поток редиректа/снятия зовёт clear в начале — не прячем панель, а показываем «идёт…»
    if (running && (jobMode === "redirect" || jobMode === "decline" || jobMode === "accept_names")) {
      set({ decline: busyDeclinePanel(jobMode), declineResultOpen: false });
      return;
    }
    set({ decline: emptyProgress("Результат"), declineResultOpen: false });
  },

  dismissDeclineResult: () =>
    set({
      declineResultOpen: false,
      decline: emptyProgress("Результат"),
    }),

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
    if (!get().dialog.open) {
      const bits = [item.amount, item.card, who].filter(Boolean);
      void get().openDialog({
        title: "Списание отменили",
        body: bits.join(" · ") || "Перевод не прошёл",
        danger: true,
        alert: true,
      });
    }
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
          confirmLabel: opts.confirmLabel,
          cancelLabel: opts.cancelLabel,
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
