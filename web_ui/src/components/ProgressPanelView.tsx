import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { WorkPulse } from "@/components/WorkPulse";
import { api, apiCall } from "@/lib/api";
import type { DealRow, ProgressPanel } from "@/lib/types";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

export function ProgressPanelView({
  panel,
  mode = "default",
}: {
  panel: ProgressPanel;
  mode?: "pipeline" | "receipts" | "decline" | "default";
}) {
  if (!panel.visible) return null;
  if (mode === "decline" && panel.processing && !panel.done) return null;

  const phase = panel.phase || "";
  const isUploading = mode === "receipts" && phase === "processing";
  const busyVisual = isUploading;
  const showBar =
    panel.processing &&
    !panel.done &&
    (mode !== "receipts" ||
      phase === "processing" ||
      (phase === "waiting" && (panel.progress ?? 0) > 0));
  const indeterminate =
    showBar && (panel.progress == null || (busyVisual && panel.progress === 0));
  const barWidth =
    showBar && !indeterminate && panel.progress != null
      ? Math.max(0, Math.min(100, panel.progress * 100))
      : undefined;

  const nested = mode === "decline";

  return (
    <div
      className={cn(
        nested
          ? "p-0"
          : "mt-3 overflow-hidden rounded-xl border bg-muted/20 p-3",
        !nested && panel.processing && !panel.done && !busyVisual && "border-slate-300",
        !nested && busyVisual && "border-amber-300 bg-amber-50/50",
        !nested && panel.done && !panel.hasErrors && "border-emerald-200 bg-emerald-50/40",
        !nested && panel.done && panel.hasErrors && "border-amber-200",
      )}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div
          className={cn(
            "flex items-center gap-2 text-[11px] font-bold uppercase tracking-wide",
            busyVisual ? "text-amber-800" : "text-muted-foreground",
          )}
        >
          {busyVisual && <WorkPulse size="sm" tone="amber" />}
          {panel.processing && !panel.done && !busyVisual && (
            <WorkPulse size="sm" tone="slate" />
          )}
          {panel.title}
        </div>
        <div
          className={cn(
            "font-mono text-xs",
            busyVisual ? "font-semibold text-amber-900" : "text-slate-600",
          )}
        >
          {panel.summary}
        </div>
      </div>

      {showBar && !indeterminate && barWidth != null && (
        <div className="relative h-1.5 overflow-hidden rounded-full bg-slate-100">
          <span
            className={cn(
              "block h-full origin-left rounded-full transition-transform duration-500 ease-out",
              busyVisual ? "bg-amber-500" : "bg-slate-800",
            )}
            style={{ transform: `scaleX(${barWidth / 100})` }}
          />
        </div>
      )}

      {busyVisual && (
        <p className="relative mt-2 text-sm font-medium text-amber-900">
          {panel.message || "Загрузка…"}
        </p>
      )}
      {panel.message && !panel.done && !busyVisual && (
        <p className="relative mt-2 text-sm text-muted-foreground">{panel.message}</p>
      )}
      {panel.deals.length > 0 && (
        <ul className={cn("relative space-y-1.5", showBar || panel.message ? "mt-2" : "")}>
          {panel.deals.map((d) => (
            <DealItem
              key={d.id}
              deal={d}
              mode={mode}
              allowCancel={!!panel.allowCancel}
              actionsDisabled={panel.phase === "processing"}
            />
          ))}
        </ul>
      )}
      {panel.errorDetail && (
        <pre className="relative mt-2 whitespace-pre-wrap rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">
          {panel.errorDetail}
        </pre>
      )}
    </div>
  );
}

function statusMeta(state: string, previewHint?: string, error?: string) {
  if (previewHint) {
    const ready =
      previewHint.includes("найден") ||
      previewHint.includes("готов") ||
      previewHint.includes("загружен");
    return {
      label: previewHint,
      className: ready
        ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
        : "bg-slate-100 text-slate-700",
    };
  }
  if (error && (state === "error" || state === "skipped")) {
    return {
      label: error,
      className:
        state === "skipped"
          ? "bg-amber-50 text-amber-800 border border-amber-200"
          : "bg-red-50 text-red-700 border border-red-200",
    };
  }
  switch (state) {
    case "paying":
      return {
        label: "Отправляю перевод…",
        className: "bg-emerald-50 text-emerald-700 border border-emerald-200",
      };
    case "accepting":
      return {
        label: "Принимаю сделку…",
        className: "bg-emerald-50 text-emerald-700 border border-emerald-200",
      };
    case "accepted":
      return {
        label: "Принята",
        className: "bg-emerald-50 text-emerald-700 border border-emerald-200",
      };
    case "paid":
    case "done":
      return {
        label: "Оплачено",
        className: "bg-emerald-100 text-emerald-800 border border-emerald-300",
      };
    case "searching":
    case "pending":
      return {
        label: state === "searching" ? "Поиск…" : "ожидает файлы",
        className: "bg-teal-50 text-teal-700 border border-teal-200",
      };
    case "matched":
      return {
        label: "файлы найдены",
        className: "bg-emerald-50 text-emerald-700 border border-emerald-200",
      };
    case "uploading":
      return {
        label: "загрузка…",
        className: "bg-amber-100 text-amber-900 border border-amber-300",
      };
    case "skipped":
      return {
        label: "пропуск — Отмена",
        className: "bg-amber-50 text-amber-800 border border-amber-200",
      };
    case "cancelling":
      return {
        label: "отмена…",
        className: "bg-amber-50 text-amber-800 border border-amber-200",
      };
    case "cancelled":
      return {
        label: "отменена",
        className: "bg-slate-100 text-slate-600 border border-slate-200",
      };
    case "error":
      return {
        label: "ошибка",
        className: "bg-red-50 text-red-700 border border-red-200",
      };
    default:
      return {
        label: state || "",
        className: "bg-slate-100 text-slate-600",
      };
  }
}

function DealItem({
  deal: d,
  mode,
  allowCancel,
  actionsDisabled,
}: {
  deal: DealRow;
  mode: "pipeline" | "receipts" | "decline" | "default";
  allowCancel: boolean;
  actionsDisabled: boolean;
}) {
  const appendLog = useConsole((s) => s.appendLog);
  const openDialog = useConsole((s) => s.openDialog);

  const state = d.state || d.status || "";
  const showFlags =
    mode === "receipts" &&
    (state === "pending" ||
      state === "matched" ||
      state === "uploading" ||
      (state === "error" && !!d.has_shot));

  const showRetry = mode === "receipts" && allowCancel && !!d.can_retry && !!d.order_id;
  const showRescan = mode === "receipts" && allowCancel && !!d.can_rescan && !!d.order_id;
  const showCancel = mode === "receipts" && allowCancel && !!d.can_cancel && !!d.order_id;

  const meta = statusMeta(
    state,
    mode === "receipts"
      ? d.preview_hint ||
          (d.has_shot
            ? d.needs_video && !d.has_video
              ? "чек есть, ждём видео"
              : "чек найден"
            : undefined)
      : undefined,
    d.error,
  );

  const onErr = (e: string) => appendLog(`[ОШИБКА] ${e}`);

  const cancelDeal = async () => {
    if (!d.order_id) return;
    const ok = await openDialog({
      title: "Отменить сделку",
      body: `№${d.index} · ${d.card || "карта?"}`,
      danger: true,
      confirmLabel: "Отменить",
    });
    if (!ok) return;
    await apiCall(() => api().cancel_completion_deal(d.order_id!), onErr);
  };

  const retryDeal = async () => {
    if (!d.order_id) return;
    const ok = await openDialog({
      title: "Повторить чек",
      body: `№${d.index} · ${d.card || "карта?"}`,
      confirmLabel: "Повторить",
    });
    if (!ok) return;
    await apiCall(() => api().retry_completion_deal(d.order_id!), onErr);
  };

  const rescanDeal = async () => {
    if (!d.order_id) return;
    const ok = await openDialog({
      title: "Другой файл",
      body: `№${d.index} · ${d.card || "карта?"}`,
      confirmLabel: "Сбросить",
    });
    if (!ok) return;
    await apiCall(() => api().rescan_completion_deal(d.order_id!), onErr);
  };

  return (
    <li
      className={cn(
        "rounded-lg border bg-white px-3 py-2.5 text-xs transition-colors",
        d.active && "border-emerald-200 bg-emerald-50/40",
        state === "uploading" && "border-amber-300 bg-amber-50/70",
        (state === "paid" || state === "done") && "border-emerald-200 bg-emerald-50/70",
        state === "skipped" && "opacity-80 border-border",
        state !== "paid" &&
          state !== "done" &&
          state !== "skipped" &&
          state !== "uploading" &&
          !d.active &&
          "border-border",
      )}
    >
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-2">
        <div className="min-w-0 space-y-1.5">
          <div className="truncate font-semibold text-sm leading-snug">
            <span className="mr-1.5 font-mono text-muted-foreground">#{d.index}</span>
            {d.holder || "—"}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {d.card && (
              <span className="font-mono text-muted-foreground">{d.card}</span>
            )}
            {meta.label && (
              <span
                className={cn(
                  "rounded-md px-1.5 py-0.5 text-[11px] font-semibold",
                  meta.className,
                )}
              >
                {meta.label}
              </span>
            )}
          </div>
          {showFlags && (
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant={d.has_shot ? "success" : "secondary"}>
                {d.has_shot ? "Чек есть" : "Нет чека"}
              </Badge>
              {d.needs_video && (
                <Badge variant={d.has_video ? "success" : "secondary"}>
                  {d.has_video ? "Видео есть" : "Нет видео"}
                </Badge>
              )}
              {d.file_name && (
                <span className="max-w-full truncate font-mono text-[10px] text-muted-foreground">
                  {d.file_name}
                </span>
              )}
            </div>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          {d.amount && (
            <span className="whitespace-nowrap font-mono text-sm font-semibold text-emerald-700">
              {d.amount}
            </span>
          )}
          {(showRetry || showRescan || showCancel) && (
            <div className="flex flex-wrap justify-end gap-1.5">
              {showRetry && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={actionsDisabled}
                  onClick={() => void retryDeal()}
                >
                  Повторить
                </Button>
              )}
              {showRescan && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={actionsDisabled}
                  onClick={() => void rescanDeal()}
                >
                  Новый файл
                </Button>
              )}
              {showCancel && (
                <Button
                  size="sm"
                  variant="danger"
                  disabled={actionsDisabled}
                  onClick={() => void cancelDeal()}
                >
                  Отменить
                </Button>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}
