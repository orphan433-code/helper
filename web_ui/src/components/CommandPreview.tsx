import { useEffect, useState } from "react";
import { ArrowRight, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { RippleButton } from "@/components/ui/ripple-button";
import { TRADERS } from "@/lib/types";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

export type AgentPlan = Record<string, unknown>;

export type PreviewDeal = {
  order_id?: string;
  card?: string;
  holder?: string;
  amount?: string;
  bank?: string;
  remaining?: string;
};

export type AgentPreview = {
  ok?: boolean;
  summary?: string;
  matched?: number;
  total_pool?: number;
  deals?: PreviewDeal[];
  plan?: AgentPlan;
  error?: string;
  steps?: { step?: string; detail?: string }[];
  token_source?: string;
  debug?: string[];
  skipped?: Record<string, number>;
};

const RESULT_CARD =
  "rounded-2xl border border-border/40 bg-background/85 shadow-lg backdrop-blur-xl";
const BTN_PRIMARY =
  "btn-cta border-primary bg-primary text-primary-foreground hover:brightness-105";
const BTN_SECONDARY =
  "border-border/50 bg-background/70 text-foreground hover:bg-foreground/[0.06]";

export function actionStyle(action: "decline" | "redirect") {
  if (action === "redirect") {
    return {
      badge: "bg-foreground/8 text-foreground ring-1 ring-border/60",
      label: "text-foreground",
      card: "ring-1 ring-border/50",
    };
  }
  return {
    badge: "bg-danger-soft text-danger ring-1 ring-danger/20",
    label: "text-danger",
    card: "ring-1 ring-danger/15",
  };
}

export function ActionBadge({ action }: { action: "decline" | "redirect" }) {
  const style = actionStyle(action);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-lg px-2.5 py-1 text-sm font-semibold",
        style.badge,
      )}
    >
      {action === "redirect" ? "Редирект" : "Отмена"}
    </span>
  );
}

export function buildUiContext(
  settings: ReturnType<typeof useConsole.getState>["settings"],
) {
  const redirect_bins = settings.redirectBinList.filter((p) => settings.redirectBins[p]);
  const decline_bins = settings.declineBinList.filter((p) => settings.declineBins[p]);
  const redirect_selected_trader_ids = TRADERS.filter((t) => settings.redirAccounts[t.id]).map(
    (t) => t.traderId,
  );
  return {
    decline_bins,
    decline_tbc: settings.declineTbc,
    decline_min_amount: settings.declineMinAmt,
    decline_max_amount: settings.declineMaxAmt,
    decline_service: settings.declineService,
    redirect_bins,
    redirect_skip_bog: settings.redirSkipBog,
    redirect_visa_only: settings.redirVisaOnly,
    redirect_max_remaining: settings.redirMaxRemaining,
    redirect_min_amount: settings.redirMin,
    redirect_max_amount: settings.redirMaxAmt,
    redirect_selected_trader_ids,
  };
}

type RequestSummary = {
  action: "decline" | "redirect";
  actionLabel: string;
  highlights: { label: string; value: string }[];
  extras: string[];
  traders: string[];
};

export function buildRequestSummary(plan: AgentPlan | null): RequestSummary | null {
  if (!plan) return null;

  const action = String(plan.action || "decline");
  const isRedirect = action === "redirect";
  const highlights: { label: string; value: string }[] = [];

  highlights.push({
    label: "лимит",
    value: plan.all_matching ? "все" : `${String(plan.max_per_run ?? 10)} шт`,
  });

  const bins = isRedirect
    ? (plan.redirect_bins as string[] | undefined) || []
    : (plan.decline_bins as string[] | undefined) || [];
  if (bins.length) highlights.push({ label: "BIN", value: bins.join(", ") });

  const minA = plan.min_amount;
  const maxA = plan.max_amount;
  if (minA != null || maxA != null) {
    const bits: string[] = [];
    if (minA != null && minA !== "") bits.push(`от ${String(minA)}`);
    if (maxA != null && maxA !== "") bits.push(`до ${String(maxA)}`);
    highlights.push({ label: "сумма", value: `${bits.join(" ")} USDT` });
  }

  const extras: string[] = [];
  const status = String(plan.deal_status || "new").toUpperCase();
  if (status !== "NEW") extras.push(`пул ${status}`);

  const traders: string[] = [];
  if (isRedirect) {
    const prefs = (plan.redirect_card_prefixes as string[] | undefined) || [];
    if (prefs.length) extras.push(`карты ${prefs.map((p) => `${p}*`).join(", ")}`);
    const labels = (plan.trader_labels as string[] | undefined) || [];
    const ids = (plan.trader_ids as string[] | undefined) || [];
    if (labels.length) {
      traders.push(...labels);
    } else if (ids.length) {
      const mapped = ids
        .map((id) => TRADERS.find((t) => t.traderId === id)?.label)
        .filter((label): label is NonNullable<typeof label> => Boolean(label));
      if (mapped.length) traders.push(...mapped);
      else extras.push(`${ids.length} акк.`);
    }
  } else {
    if (plan.decline_tbc) extras.push("TBC");
    const prefs = (plan.decline_card_prefixes as string[] | undefined) || [];
    if (prefs.length) extras.push(`карты ${prefs.map((p) => `${p}*`).join(", ")}`);
    const svc = String(plan.service || "").toUpperCase();
    if (svc) extras.push(svc);
  }

  if (plan.max_remaining) {
    extras.push(`остаток < ${String(plan.max_remaining_hours ?? 1)} ч`);
  }
  if (plan.visa_only) extras.push("только Visa");
  if (plan.mastercard_only) extras.push("только Mastercard");
  if (plan.skip_bog) extras.push("без BoG");

  return {
    action: isRedirect ? "redirect" : "decline",
    actionLabel: isRedirect ? "Редирект" : "Отмена",
    highlights,
    extras,
    traders,
  };
}

export function dealWord(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return "сделок";
  if (mod10 === 1) return "сделка";
  if (mod10 >= 2 && mod10 <= 4) return "сделки";
  return "сделок";
}

function CountUp({ value }: { value: number }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const start = performance.now();
    const from = 0;
    const dur = 400;
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      setN(Math.round(from + (value - from) * eased));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <>{n}</>;
}

export function CommandPreviewPanel({
  plan,
  preview,
  busy,
  loading,
  disabled,
  onConfirm,
  onCancel,
  cancelLabel = "Сброс",
}: {
  plan: AgentPlan | null;
  preview: AgentPreview | null;
  busy?: "parse" | "preview" | "execute" | null;
  loading?: boolean;
  disabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  cancelLabel?: string;
}) {
  const req = buildRequestSummary(plan);
  const matched = preview?.matched ?? 0;
  const poolStatus = plan?.deal_status ? String(plan.deal_status).toUpperCase() : "NEW";
  const extrasOnly = (req?.extras || []).join(" · ");
  const amountHighlight = req?.highlights.find((h) => h.label === "сумма");
  const extrasDisplay = [amountHighlight?.value, extrasOnly].filter(Boolean).join(" · ");
  const restWithoutAmount = req
    ? req.highlights
        .filter((h) => h.label !== "сумма")
        .map((h) => (h.label === "BIN" ? `BIN ${h.value}` : h.value))
        .join(" · ")
    : "";
  const accent = req ? actionStyle(req.action) : null;
  const confirmBusy = busy === "execute";
  const locked = loading || confirmBusy || !!disabled;

  if (loading && !preview) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-10">
        <Loader2 className="size-8 animate-spin text-muted-foreground" />
        <p className="text-sm font-medium text-muted-foreground">Ищу сделки…</p>
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className={cn(RESULT_CARD, "p-4")}>
          <h3 className="mb-3 text-sm font-semibold text-neutral-600">
            {matched > 0 ? "Найдено" : "Не найдено"}
          </h3>
          {matched > 0 ? (
            <div className="flex items-end gap-2">
              <span className="text-5xl font-bold leading-none tabular-nums text-foreground">
                <CountUp value={matched} />
              </span>
              <span className="pb-1.5 text-base font-semibold text-foreground/55">
                {dealWord(matched)}
              </span>
            </div>
          ) : (
            <p className="text-sm font-medium text-muted-foreground">Подходящих сделок нет</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">
              в пуле {preview?.total_pool ?? "—"}
            </span>
            <Badge variant="success" className="font-mono text-[10px]">
              {poolStatus}
            </Badge>
          </div>
        </div>

        <div className={cn(RESULT_CARD, "p-4", accent?.card)}>
          <h3 className="mb-3 text-sm font-semibold text-neutral-600">Запрос</h3>
          {req ? (
            <div className="space-y-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <ActionBadge action={req.action} />
                {restWithoutAmount && (
                  <span className={cn("text-sm font-medium", accent?.label)}>
                    {restWithoutAmount}
                  </span>
                )}
              </div>
              {extrasDisplay && (
                <p className="text-xs text-muted-foreground">{extrasDisplay}</p>
              )}
              {req.traders.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] text-muted-foreground">куда</span>
                  {req.traders.map((t) => (
                    <Badge key={t} variant="secondary" className="text-[11px]">
                      {t}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">—</p>
          )}
        </div>
      </div>

      {preview?.deals && preview.deals.length > 0 && (
        <div className={cn(RESULT_CARD, "p-4")}>
          <h3 className="mb-3 text-sm font-semibold text-neutral-600">Сделки</h3>
          <div className="overflow-hidden rounded-xl border border-slate-100">
            <div className="grid grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)_minmax(0,0.9fr)_minmax(0,0.75fr)] gap-2 border-b border-border/40 bg-background/50 px-3 py-2.5 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
              <span>order</span>
              <span>карта</span>
              <span>сумма</span>
              <span>остаток</span>
            </div>
            <div className="max-h-[min(42vh,320px)] overflow-y-auto bg-background/40">
              {preview.deals.map((d, i) => (
                <div
                  key={d.order_id || `${d.card}-${d.amount}-${i}`}
                  className={cn(
                    "grid grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)_minmax(0,0.9fr)_minmax(0,0.75fr)] gap-2 px-3 py-3 text-sm",
                    i % 2 === 1 && "bg-slate-50/50",
                  )}
                >
                  <span className="truncate font-mono text-xs">{d.order_id || "—"}</span>
                  <span className="truncate">{d.card || "—"}</span>
                  <span className="truncate tabular-nums">{d.amount || "—"}</span>
                  <span className="truncate tabular-nums">{d.remaining || "—"}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <RippleButton
          type="button"
          disabled={locked || !plan || matched === 0}
          onClick={onConfirm}
          rippleColor="#e7e2d9"
          className={`${BTN_PRIMARY} h-12 px-6 text-base`}
        >
          {confirmBusy ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Запуск…
            </>
          ) : (
            <>
              Запустить
              <ArrowRight className="size-4" />
            </>
          )}
        </RippleButton>
        <RippleButton
          type="button"
          onClick={onCancel}
          disabled={confirmBusy}
          rippleColor="#e7e2d9"
          className={BTN_SECONDARY}
        >
          {cancelLabel}
        </RippleButton>
      </div>
    </div>
  );
}
