import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, apiCall } from "@/lib/api";
import type { DealRow, ProgressPanel } from "@/lib/types";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

export function ProgressPanelView({
  panel,
  mode = "default",
}: {
  panel: ProgressPanel;
  mode?: "pipeline" | "receipts" | "default";
}) {
  if (!panel.visible) return null;

  // Полоска только пока идёт работа; готово — без строки, просто зелёный статус
  const showBar = panel.processing && !panel.done;
  const indeterminate = showBar && panel.progress == null;
  const barWidth =
    showBar && !indeterminate && panel.progress != null
      ? `${Math.max(0, Math.min(100, panel.progress * 100))}%`
      : undefined;

  return (
    <div
      className={cn(
        "mt-3 rounded-xl border bg-muted/20 p-3",
        panel.processing && !panel.done && "border-slate-300",
        panel.done && !panel.hasErrors && "border-emerald-200 bg-emerald-50/40",
        panel.done && panel.hasErrors && "border-amber-200",
      )}
    >
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <div className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
          {panel.title}
        </div>
        <div className="font-mono text-xs text-slate-600">{panel.summary}</div>
      </div>
      {showBar && (
        <div
          className={cn(
            "h-1.5 overflow-hidden rounded-full bg-slate-100",
            indeterminate && "pbar-indeterminate",
          )}
        >
          <span
            className={cn(
              "block h-full rounded-full bg-emerald-500/90",
              !indeterminate && "transition-all",
            )}
            style={barWidth ? { width: barWidth } : undefined}
          />
        </div>
      )}
      {panel.message && !panel.done && (
        <p className="mt-2 text-sm text-muted-foreground">{panel.message}</p>
      )}
      {panel.deals.length > 0 && (
        <ul className={cn("max-h-64 space-y-1.5 overflow-auto", showBar || panel.message ? "mt-2" : "")}>
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
        <pre className="mt-2 whitespace-pre-wrap rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">
          {panel.errorDetail}
        </pre>
      )}
    </div>
  );
}

function statusMeta(state: string, previewHint?: string, error?: string) {
  if (previewHint) {
    return { label: previewHint, className: "bg-slate-100 text-slate-700" };
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
        className: "bg-emerald-50 text-emerald-700 border border-emerald-200",
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
  mode: "pipeline" | "receipts" | "default";
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
    mode === "receipts" ? d.preview_hint : undefined,
    d.error,
  );

  const onErr = (e: string) => appendLog(`[ОШИБКА] ${e}`);

  const cancelDeal = async () => {
    if (!d.order_id) return;
    const ok = await openDialog({
      title: "Отмена сделки",
      body:
        `Отменить сделку ${d.index} (карта ${d.card || "????"})?\n\n` +
        "Сделка будет отменена без чека.",
      danger: true,
    });
    if (!ok) return;
    await apiCall(() => api().cancel_completion_deal(d.order_id!), onErr);
  };

  const retryDeal = async () => {
    if (!d.order_id) return;
    const ok = await openDialog({
      title: "Повтор отправки",
      body:
        `Повторить отправку чека по сделке ${d.index} (карта ${d.card || "????"})?\n\n` +
        "Чек уже найден. Бот снова загрузит его и подтвердит выплату.",
    });
    if (!ok) return;
    await apiCall(() => api().retry_completion_deal(d.order_id!), onErr);
  };

  const rescanDeal = async () => {
    if (!d.order_id) return;
    const ok = await openDialog({
      title: "Новый файл",
      body:
        `Сбросить чек по сделке ${d.index} (карта ${d.card || "????"})?\n\n` +
        "Положи новый файл и снова нажми «Загрузить».",
    });
    if (!ok) return;
    await apiCall(() => api().rescan_completion_deal(d.order_id!), onErr);
  };

  return (
    <li
      className={cn(
        "rounded-lg border bg-white px-2.5 py-2 text-xs",
        d.active && "border-emerald-200 bg-emerald-50/40",
        (state === "paid" || state === "done") &&
          "border-emerald-200 bg-emerald-50/70",
        state === "skipped" && "opacity-80 border-border",
        state !== "paid" &&
          state !== "done" &&
          state !== "skipped" &&
          !d.active &&
          "border-border",
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold">
          <span className="mr-2 font-mono text-muted-foreground">#{d.index}</span>
          {d.holder || "—"}
        </span>
        {d.amount && (
          <span className="font-mono text-sm font-semibold text-emerald-700">
            {d.amount}
          </span>
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        {d.card && <span className="font-mono text-muted-foreground">{d.card}</span>}
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
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Badge variant={d.has_shot ? "success" : "secondary"}>
            {d.has_shot ? "Чек есть" : "Нет чека"}
          </Badge>
          {d.needs_video && (
            <Badge variant={d.has_video ? "success" : "secondary"}>
              {d.has_video ? "Видео есть" : "Нет видео"}
            </Badge>
          )}
          {d.file_name && (
            <span className="truncate font-mono text-[10px] text-muted-foreground">
              {d.file_name}
            </span>
          )}
        </div>
      )}
      {(showRetry || showRescan || showCancel) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
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
    </li>
  );
}
