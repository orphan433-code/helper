type Api = {
  get_state: () => Promise<Record<string, unknown>>;
  poll_logs: () => Promise<unknown>;
  check_adb: () => Promise<Record<string, unknown>>;
  get_update_status: () => Promise<Record<string, unknown>>;
  apply_app_update: () => Promise<Record<string, unknown>>;
  save_settings: (
    max_deals: number,
    min_amount: string,
    max_amount: string,
    allow_visa: boolean,
    allow_mastercard: boolean,
    max_empty_list_passes: number,
    from_pending: boolean,
  ) => Promise<Record<string, unknown>>;
  save_redirect_filters: (
    skip_bog: boolean,
    visa_only: boolean,
    max_remaining: boolean,
  ) => Promise<Record<string, unknown>>;
  start_pipeline: (
    max_deals: number,
    min_amount: string,
    max_amount: string,
    allow_visa: boolean,
    allow_mastercard: boolean,
    max_empty_list_passes: number,
    from_pending: boolean,
  ) => Promise<Record<string, unknown>>;
  start_login: () => Promise<Record<string, unknown>>;
  stop_job: () => Promise<Record<string, unknown>>;
  confirm: (kind?: string) => Promise<Record<string, unknown>>;
  cancel_completion_deal: (order_id: string) => Promise<Record<string, unknown>>;
  retry_completion_deal: (order_id: string) => Promise<Record<string, unknown>>;
  rescan_completion_deal: (order_id: string) => Promise<Record<string, unknown>>;
  preview_receipts: () => Promise<Record<string, unknown>>;
  recovery_retry: () => Promise<Record<string, unknown>>;
  recovery_continue: () => Promise<Record<string, unknown>>;
  recovery_exit: () => Promise<Record<string, unknown>>;
  open_videos_folder: () => Promise<Record<string, unknown>>;
  open_screens_folder: () => Promise<Record<string, unknown>>;
  start_decline: (
    prefixes: string[],
    tbc?: boolean,
  ) => Promise<Record<string, unknown>>;
  start_redirect: (
    trader_ids: string[],
    max_per_run: number,
    min_amount: string | number | null,
    max_amount: string | number | null,
    deal_status: string,
    skip_bog: boolean,
    visa_only: boolean,
    max_remaining: boolean,
  ) => Promise<Record<string, unknown>>;
};

declare global {
  interface Window {
    pywebview?: { api: Api };
    applyState?: (state: Record<string, unknown>) => void;
    setStatus?: (text: string, state?: string) => void;
    setRunning?: (running: boolean, jobMode?: string, keepStatus?: boolean) => void;
    appendLog?: (text: string) => void;
    ingestLogEvents?: (events: unknown[]) => void;
    updatePipelineProgress?: (payload: Record<string, unknown>) => void;
    clearPipelineProgress?: () => void;
    updateReceiptProgress?: (payload: Record<string, unknown>) => void;
    clearReceiptProgress?: () => void;
    updateDeclineResult?: (payload: Record<string, unknown>) => void;
    clearDeclineResult?: () => void;
    appendCancelAlert?: (payload: Record<string, unknown>) => void;
    clearCancelAlerts?: () => void;
    setConfirmPrompt?: (prompt: string, mode: string) => void;
    setRecoveryPrompt?: (
      message: string,
      detail: string,
      hint: string,
      summary: Record<string, unknown>,
      allowRetry: boolean,
    ) => void;
    hideRecoveryPrompt?: () => void;
    grabWindowAttention?: (prefix?: string, detail?: string) => void;
    clearTitleAttention?: () => void;
    showConfirm?: (
      message: string,
      opts?: { title?: string; confirmLabel?: string; cancelLabel?: string; danger?: boolean },
    ) => Promise<boolean>;
    __videoMinUsdt?: number;
  }
}

export function api(): Api {
  if (!window.pywebview?.api) {
    throw new Error("API недоступен — bridge ещё не готов");
  }
  return window.pywebview.api;
}

export async function apiCall<T extends Record<string, unknown>>(
  fn: () => Promise<T>,
  onError: (msg: string) => void,
): Promise<T | undefined> {
  try {
    const result = await fn();
    if (result && typeof result.error === "string" && result.error) {
      onError(result.error);
    }
    return result;
  } catch (err) {
    onError(String(err));
    return undefined;
  }
}

export async function serverPost(path: string, body?: unknown) {
  const r = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(await r.text());
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("application/json")) return r.json();
  return {};
}
