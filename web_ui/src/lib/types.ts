export type StatusKind = "idle" | "running" | "waiting" | "success" | "error";

export type DealRow = {
  id?: string;
  index?: number | string;
  holder?: string;
  amount?: string;
  card?: string;
  status?: string;
  state?: string;
  error?: string;
  ok?: boolean;
  active?: boolean;
  order_id?: string;
  has_shot?: boolean;
  has_video?: boolean;
  needs_video?: boolean;
  preview_ready?: boolean;
  preview_hint?: string;
  file_name?: string;
  can_cancel?: boolean;
  can_retry?: boolean;
  can_rescan?: boolean;
};

export type ProgressPanel = {
  visible: boolean;
  processing: boolean;
  done: boolean;
  title: string;
  summary: string;
  message: string;
  deals: DealRow[];
  success?: string;
  errorDetail?: string;
  hasErrors?: boolean;
  /** 0..1 для полоски; undefined = pulse при processing */
  progress?: number;
  phase?: string;
  allowCancel?: boolean;
};

export type CancelAlert = {
  id: string;
  amount?: string;
  ts?: string;
  card?: string;
  balance?: string;
  match_label?: string;
  match_holder?: string;
  match_index?: string | number;
  match_card?: string;
  match_amount_tjs?: string | number;
  raw?: string;
};

export type RecoveryState = {
  open: boolean;
  message: string;
  detail: string;
  hint: string;
  allowRetry: boolean;
  continueLabel: string;
  deal: {
    index?: string;
    card?: string;
    holder?: string;
    amount_tjs?: string;
    amount_target?: string;
  } | null;
};

export type LogEvent = {
  id: number;
  time?: string;
  level?: string;
  service?: string;
  message?: string;
  status?: string;
  tags?: string[];
  raw?: Record<string, unknown>;
};

export type DialogState = {
  open: boolean;
  title: string;
  body: string;
  danger?: boolean;
  /** Только кнопка OK, без «Назад» (итог операции). */
  alert?: boolean;
  confirmLabel?: string;
  cancelLabel?: string;
  resolve?: (ok: boolean) => void;
};

export const IDLE_STATUS = "Можно запускать";

export const TRADERS = [
  {
    id: "redir-104-1",
    label: "104.1",
    traderId: "925b6a0e-9222-44f6-89bd-f25a688909d7",
  },
  {
    id: "redir-104-2",
    label: "104.2",
    traderId: "00c5b405-2f9b-49ad-bbf8-b2a6167f3af8",
  },
  {
    id: "redir-104-3",
    label: "104.3",
    traderId: "fcfc51a9-0171-41ef-9e67-ba01757ec603",
  },
] as const;
