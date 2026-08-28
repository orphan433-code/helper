import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import {
  ArrowRight,
  CreditCard,
  History,
  Loader2,
  Send,
  Star,
  Trash2,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { BentoGrid } from "@/components/ui/bento-grid";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { RippleButton } from "@/components/ui/ripple-button";
import { Switch } from "@/components/ui/switch";
import { serverGet, serverPost } from "@/lib/api";
import {
  BANK_BINS,
  buildBinCommand,
  formatBinMask,
  type BankBinRow,
} from "@/lib/bankBins";
import { TRADERS } from "@/lib/types";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

type AgentPlan = Record<string, unknown>;

type PreviewDeal = {
  order_id?: string;
  card?: string;
  holder?: string;
  amount?: string;
  bank?: string;
  remaining?: string;
};

type AgentPreview = {
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

type HistoryItem = {
  text: string;
  summary: string;
  hits: number;
  last_used: number;
  source: string;
  favorite?: boolean;
};

const BTN_PRIMARY = "border-primary bg-primary text-primary-foreground hover:brightness-105";
const BTN_SECONDARY =
  "border-border bg-card text-foreground hover:bg-muted/60";
const BTN_GHOST =
  "h-8 border-transparent bg-transparent px-2 text-xs text-muted-foreground hover:bg-muted/60";

const RESULT_CARD =
  "rounded-2xl bg-white shadow-[0_0_0_1px_rgba(0,0,0,.04),0_2px_8px_rgba(15,23,42,.04)]";

function actionStyle(action: "decline" | "redirect") {
  if (action === "redirect") {
    return {
      badge: "bg-blue-50 text-blue-900 ring-1 ring-blue-200/80",
      label: "text-blue-900",
      card: "ring-1 ring-blue-200/60",
    };
  }
  return {
    badge: "bg-rose-50 text-rose-800 ring-1 ring-rose-200/80",
    label: "text-rose-800",
    card: "ring-1 ring-rose-200/60",
  };
}

function ActionBadge({ action }: { action: "decline" | "redirect" }) {
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

function buildUiContext(settings: ReturnType<typeof useConsole.getState>["settings"]) {
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

function buildRequestSummary(plan: AgentPlan | null): RequestSummary | null {
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

function dealWord(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return "сделок";
  if (mod10 === 1) return "сделка";
  if (mod10 >= 2 && mod10 <= 4) return "сделки";
  return "сделок";
}

function historyAction(item: HistoryItem): "decline" | "redirect" {
  const hay = `${item.text} ${item.summary}`.toLowerCase();
  return /редирект|redirect/.test(hay) ? "redirect" : "decline";
}

type HistoryParam = { label: string; value: string };

function parseHistoryParams(summary: string): { main: HistoryParam[]; extras: string[] } {
  const raw = summary.trim();
  if (!raw) return { main: [], extras: [] };

  const main: HistoryParam[] = [];
  const extras: string[] = [];

  const pushMain = (label: string, value: string) => {
    const v = value.trim();
    if (v) main.push({ label: label.toLowerCase(), value: v });
  };

  if (raw.includes("\n")) {
    for (const line of raw.split("\n")) {
      const t = line.trim();
      if (!t) continue;

      const colon = t.indexOf(": ");
      if (colon > 0) {
        pushMain(t.slice(0, colon), t.slice(colon + 2));
        continue;
      }

      const dash = t.indexOf(" — ");
      if (dash > 0) {
        const head = t.slice(0, dash);
        const tail = t.slice(dash + 3);
        if (/все подходящие/i.test(tail)) {
          pushMain("лимит", "все");
        } else if (/^(отмена|редирект)$/i.test(head) && /до \d+/i.test(tail)) {
          pushMain("лимит", tail.replace(/сделок/i, "шт").replace(/\.$/, ""));
        } else {
          extras.push(t);
        }
        continue;
      }

      extras.push(t);
    }
    return { main, extras };
  }

  for (const part of raw.split(" · ").map((s) => s.trim())) {
    if (!part || part.startsWith("—") || part.startsWith("- ")) continue;

    const allMatch = part.match(/^(?:Отмена|Редирект) — все подходящие/i);
    if (allMatch) {
      pushMain("лимит", "все");
      continue;
    }

    const limitMatch = part.match(/^(?:Отмена|Редирект) до (\d+) шт\.?/i);
    if (limitMatch) {
      pushMain("лимит", `${limitMatch[1]} шт`);
      continue;
    }

    const binMatch = part.match(/^BIN (.+)/i);
    if (binMatch) {
      pushMain("BIN", binMatch[1]);
      continue;
    }

    if (/^(?:от|до) [\d.]+(?: USDT)?/i.test(part)) {
      pushMain("сумма", part.includes("USDT") ? part : `${part} USDT`);
      continue;
    }

    if (part.startsWith("→ ")) {
      pushMain("аккаунты", part.slice(2));
      continue;
    }

    if (/^(?:только Visa|без BoG|status=)/i.test(part)) {
      extras.push(part.replace(/^status=/i, "пул "));
      continue;
    }

    if (!/^(?:Отмена|Редирект)$/i.test(part)) {
      extras.push(part);
    }
  }

  return { main, extras };
}

function formatParamsLine(main: HistoryParam[]): string {
  return main
    .map((p) => {
      if (p.label === "bin") return `BIN ${p.value}`;
      if (p.label === "лимит") return p.value.replace(/\.$/, "");
      if (p.label === "сумма") return p.value;
      if (p.label === "аккаунты") return p.value;
      return p.value;
    })
    .join(" · ");
}

function AgentShell({
  children,
  toolbar,
}: {
  children: ReactNode;
  toolbar?: ReactNode;
}) {
  return (
    <div className="relative mx-auto w-full max-w-[42rem]">
      {toolbar && <div className="mb-2 flex justify-end">{toolbar}</div>}
      <BentoGrid className="w-full lg:grid-rows-[auto]">{children}</BentoGrid>
    </div>
  );
}

function AgentHeaderCta({
  selectedCount,
  historyCount,
  favoritesCount,
  onOpenKuda,
  onOpenBins,
  onOpenHistory,
}: {
  selectedCount: number;
  historyCount: number;
  favoritesCount: number;
  onOpenKuda: () => void;
  onOpenBins: () => void;
  onOpenHistory: () => void;
}) {
  return (
    <div className="flex items-center gap-1">
      <RippleButton
        type="button"
        onClick={onOpenKuda}
        rippleColor="#cbd5e1"
        className={BTN_GHOST}
      >
        Куда
        <span className="font-semibold tabular-nums text-foreground">
          {selectedCount}/{TRADERS.length}
        </span>
      </RippleButton>
      <RippleButton
        type="button"
        onClick={onOpenBins}
        rippleColor="#cbd5e1"
        className={BTN_GHOST}
        aria-label="BIN справочник"
        data-testid="bin-directory"
      >
        <CreditCard className="size-3.5" />
        BIN
      </RippleButton>
      <RippleButton
        type="button"
        onClick={onOpenHistory}
        rippleColor="#cbd5e1"
        className={BTN_GHOST}
      >
        <History className="size-3.5" />
        История
        {historyCount > 0 && (
          <span className="font-semibold tabular-nums text-foreground">{historyCount}</span>
        )}
        {favoritesCount > 0 && <Star className="size-3 fill-amber-400 text-amber-400" />}
      </RippleButton>
    </div>
  );
}

function agentToolbar(
  agentConfigured: boolean,
  selectedCount: number,
  historyCount: number,
  favoritesCount: number,
  setKudaOpen: (v: boolean) => void,
  setBinOpen: (v: boolean) => void,
  setHistoryOpen: (v: boolean) => void,
) {
  return (
    <div className="flex items-center gap-2">
      {!agentConfigured && (
        <Badge variant="warn" className="text-[10px]">
          нужен Gemini ключ
        </Badge>
      )}
      <AgentHeaderCta
        selectedCount={selectedCount}
        historyCount={historyCount}
        favoritesCount={favoritesCount}
        onOpenKuda={() => setKudaOpen(true)}
        onOpenBins={() => setBinOpen(true)}
        onOpenHistory={() => setHistoryOpen(true)}
      />
    </div>
  );
}

function CommandComposer({
  value,
  onChange,
  onSubmit,
  disabled,
  busy,
  multiline = true,
  placeholder,
  trailing,
  presets,
  onPickPreset,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  busy: "parse" | "preview" | "execute" | null;
  multiline?: boolean;
  placeholder?: string;
  trailing?: ReactNode;
  presets?: HistoryItem[];
  onPickPreset?: (text: string) => void;
}) {
  const canRun = !!value.trim();
  const busyParse = busy === "parse" || busy === "preview";
  const showPresets = multiline && !canRun && !!presets?.length && !!onPickPreset;

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  };

  const toolbar = (
    <div
      className={cn(
        "absolute right-2.5 z-10 flex items-center gap-1.5",
        multiline ? "bottom-2.5" : "top-1/2 -translate-y-1/2",
      )}
    >
      {trailing}
      <RippleButton
        type="button"
        aria-label="Отправить"
        disabled={disabled || !canRun}
        onClick={onSubmit}
        rippleColor="#cbd5e1"
        className={cn(
          "size-9 shrink-0 rounded-full border-0 p-0 shadow-sm transition-all duration-200",
          canRun && !disabled
            ? "bg-primary text-primary-foreground hover:scale-[1.04] hover:brightness-110"
            : "bg-muted text-muted-foreground",
        )}
      >
        {busyParse ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-3.5" />}
      </RippleButton>
    </div>
  );

  return (
    <div className="relative rounded-2xl bg-white">
      {multiline ? (
        <textarea
          value={value}
          rows={2}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          className={cn(
            "w-full resize-none border-0 bg-transparent px-4 py-2.5 text-[15px] leading-normal text-foreground placeholder:text-muted-foreground/80 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
            showPresets ? "min-h-[4.5rem] pb-10" : "min-h-[3.25rem] pb-11",
          )}
        />
      ) : (
        <Input
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="h-12 border-0 bg-transparent pr-14 text-[15px] shadow-none focus-visible:ring-0"
        />
      )}
      {showPresets && (
        <div className="absolute bottom-2.5 left-3 right-14 z-[5] overflow-hidden">
          <div className="flex flex-nowrap gap-1.5 overflow-x-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
            {presets!.map((item) => {
              const action = historyAction(item);
              const label = item.text.length > 24 ? `${item.text.slice(0, 24)}…` : item.text;
              return (
                <button
                  key={`${item.text}-${item.last_used}`}
                  type="button"
                  disabled={disabled}
                  title={item.text}
                  onClick={() => onPickPreset!(item.text)}
                  className={cn(
                    "max-w-[10.5rem] shrink-0 cursor-pointer truncate rounded-full px-2.5 py-1 text-left text-[11px] font-medium transition-colors duration-150 disabled:opacity-50",
                    action === "decline"
                      ? "bg-red-50 text-red-800 hover:bg-red-100"
                      : "bg-slate-100 text-slate-800 hover:bg-slate-200",
                  )}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
      )}
      {toolbar}
    </div>
  );
}

function HistoryRow({
  item,
  disabled,
  onRun,
  onToggleFavorite,
  onRemove,
}: {
  item: HistoryItem;
  disabled: boolean;
  onRun: (text: string) => void;
  onToggleFavorite: (item: HistoryItem, e: MouseEvent) => void;
  onRemove: (text: string, e: MouseEvent) => void;
}) {
  const fav = !!item.favorite;
  const action = historyAction(item);
  const actionLabel = action === "redirect" ? "редирект" : "отмена";
  const { main, extras } = parseHistoryParams(item.summary || "");
  const params = formatParamsLine(main);

  return (
    <div
      className={cn(
        "group flex items-center gap-2 rounded-xl border border-border bg-muted/25 p-3 transition hover:bg-muted/40",
        disabled && "pointer-events-none opacity-50",
      )}
    >
      <button
        type="button"
        disabled={disabled}
        onClick={() => onRun(item.text)}
        className="min-w-0 flex-1 space-y-1 text-left"
      >
        <div className="flex items-center gap-2">
          <Badge variant={action === "redirect" ? "default" : "danger"} className="text-[10px]">
            {actionLabel}
          </Badge>
          {params && (
            <span className="min-w-0 truncate text-xs font-medium text-foreground">{params}</span>
          )}
        </div>
        {extras.length > 0 && (
          <p className="truncate text-[11px] text-muted-foreground">{extras.join(" · ")}</p>
        )}
        <p className="truncate font-mono text-[10px] text-muted-foreground">{item.text}</p>
      </button>

      <div className="flex shrink-0 gap-0.5">
        <RippleButton
          type="button"
          disabled={disabled}
          aria-label={fav ? "Убрать из избранного" : "В избранное"}
          rippleColor="#fde68a"
          className="size-8 border-transparent bg-transparent p-0 text-muted-foreground hover:bg-muted/60"
          onClick={(e) => onToggleFavorite(item, e)}
        >
          <Star className={cn("size-3.5", fav && "fill-amber-400 text-amber-400")} />
        </RippleButton>
        <RippleButton
          type="button"
          disabled={disabled}
          aria-label="Удалить"
          rippleColor="#fecaca"
          className="size-8 border-transparent bg-transparent p-0 text-muted-foreground hover:bg-muted/60"
          onClick={(e) => onRemove(item.text, e)}
        >
          <X className="size-3.5" />
        </RippleButton>
      </div>
    </div>
  );
}

function AccountToggle({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-2 rounded-xl border border-border/80 bg-muted/25 px-3 py-2.5">
      <span className="text-sm font-semibold text-foreground">{label}</span>
      <Switch checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </label>
  );
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

function BinChip({
  bin,
  disabled,
  onPick,
}: {
  bin: string;
  disabled: boolean;
  onPick: (bin: string) => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      title={`Вставить ${bin}`}
      onClick={() => onPick(bin)}
      className="block w-full cursor-pointer rounded-md px-1 py-0.5 text-left font-mono text-[11px] tabular-nums text-slate-800 hover:bg-slate-100 disabled:opacity-50"
    >
      {formatBinMask(bin)}
    </button>
  );
}

function BinDirectoryPanel({
  open,
  onOpenChange,
  disabled,
  onInsert,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  disabled: boolean;
  onInsert: (text: string) => void;
}) {
  const [action, setAction] = useState<"decline" | "redirect">("decline");

  const insertBank = (row: BankBinRow) => {
    const bins = [...row.visa, ...row.mastercard];
    onInsert(buildBinCommand(action, bins));
    onOpenChange(false);
  };

  const insertBin = (bin: string) => {
    onInsert(buildBinCommand(action, [bin]));
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg gap-0 p-0">
        <div className="border-b border-border/50 px-5 pb-4 pt-5">
          <DialogHeader className="gap-1.5">
            <DialogTitle>BIN банков</DialogTitle>
            <DialogDescription>
              Клик по банку или BIN — готовый запрос отмены или редиректа в поле.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-3 flex gap-1 rounded-xl bg-muted/60 p-1">
            <button
              type="button"
              onClick={() => setAction("decline")}
              className={cn(
                "flex-1 rounded-lg px-2 py-1.5 text-xs font-semibold transition",
                action === "decline"
                  ? "bg-white text-rose-800 shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Отмена
            </button>
            <button
              type="button"
              onClick={() => setAction("redirect")}
              className={cn(
                "flex-1 rounded-lg px-2 py-1.5 text-xs font-semibold transition",
                action === "redirect"
                  ? "bg-white text-blue-900 shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Редирект
            </button>
          </div>
        </div>
        <div className="max-h-[min(60vh,28rem)] overflow-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="sticky top-0 bg-white">
              <tr className="border-b border-slate-200 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-2.5 font-bold">Банк</th>
                <th className="px-3 py-2.5 font-bold">Visa</th>
                <th className="px-3 py-2.5 font-bold">Mastercard</th>
              </tr>
            </thead>
            <tbody>
              {BANK_BINS.map((row) => (
                <tr key={row.id} className="align-top border-b border-slate-200">
                  <td className="px-4 py-2.5">
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => insertBank(row)}
                      className="cursor-pointer text-left text-xs font-bold uppercase tracking-wide text-slate-900 hover:text-primary disabled:opacity-50"
                    >
                      {row.name}
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    {row.visa.length ? (
                      row.visa.map((bin) => (
                        <BinChip key={bin} bin={bin} disabled={disabled} onPick={insertBin} />
                      ))
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {row.mastercard.length ? (
                      row.mastercard.map((bin) => (
                        <BinChip key={bin} bin={bin} disabled={disabled} onPick={insertBin} />
                      ))
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function KudaPanel({
  open,
  onOpenChange,
  settings,
  patch,
  disabled,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  settings: ReturnType<typeof useConsole.getState>["settings"];
  patch: ReturnType<typeof useConsole.getState>["patchSettings"];
  disabled: boolean;
}) {
  const selectedCount = TRADERS.filter((t) => settings.redirAccounts[t.id]).length;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md gap-0 p-0">
        <div className="border-b border-border/50 px-5 pb-4 pt-5">
          <DialogHeader className="gap-1.5">
            <DialogTitle>Куда</DialogTitle>
            <DialogDescription>
              Аккаунты для редиректа через AI. Выбрано {selectedCount} из {TRADERS.length}.
            </DialogDescription>
          </DialogHeader>
        </div>
        <div className="space-y-2 px-5 py-4">
          {TRADERS.map((t) => (
            <AccountToggle
              key={t.id}
              label={t.label}
              checked={!!settings.redirAccounts[t.id]}
              disabled={disabled}
              onChange={(v) =>
                patch({
                  redirAccounts: {
                    ...settings.redirAccounts,
                    [t.id]: v,
                  },
                })
              }
            />
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function HistoryPanel({
  open,
  onOpenChange,
  favorites,
  recent,
  disabled,
  onRun,
  onToggleFavorite,
  onRemove,
  onClear,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  favorites: HistoryItem[];
  recent: HistoryItem[];
  disabled: boolean;
  onRun: (text: string) => void;
  onToggleFavorite: (item: HistoryItem, e: MouseEvent) => void;
  onRemove: (text: string, e: MouseEvent) => void;
  onClear: () => void;
}) {
  const empty = favorites.length === 0 && recent.length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md gap-0 p-0">
        <div className="border-b border-border/50 px-5 pb-4 pt-5">
          <DialogHeader className="gap-1.5">
            <DialogTitle>История</DialogTitle>
            <DialogDescription>
              Тап — повтор без Gemini. ★ остаётся при очистке.
            </DialogDescription>
          </DialogHeader>
        </div>

        {empty ? (
          <p className="px-5 py-10 text-center text-sm text-muted-foreground">
            Пока пусто — разберите первую команду
          </p>
        ) : (
          <div className="max-h-[min(52vh,28rem)] space-y-4 overflow-y-auto px-5 py-4">
            {favorites.length > 0 && (
              <section className="space-y-2">
                <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
                  <Star className="size-3.5 fill-amber-400 text-amber-400" />
                  избранное
                </p>
                <div className="space-y-2">
                  {favorites.map((h) => (
                    <HistoryRow
                      key={`fav-${h.text}`}
                      item={h}
                      disabled={disabled}
                      onRun={onRun}
                      onToggleFavorite={onToggleFavorite}
                      onRemove={onRemove}
                    />
                  ))}
                </div>
              </section>
            )}

            {recent.length > 0 && (
              <section className="space-y-2">
                <div className="flex items-center gap-2">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
                    недавние
                  </p>
                  <RippleButton
                    type="button"
                    rippleColor="#cbd5e1"
                    className="ml-auto h-8 border-transparent bg-transparent px-2 text-xs text-muted-foreground hover:bg-muted/60"
                    onClick={onClear}
                  >
                    <Trash2 className="size-3" />
                    очистить
                  </RippleButton>
                </div>
                <div className="space-y-2">
                  {recent.map((h) => (
                    <HistoryRow
                      key={`hist-${h.text}`}
                      item={h}
                      disabled={disabled}
                      onRun={onRun}
                      onToggleFavorite={onToggleFavorite}
                      onRemove={onRemove}
                    />
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function IdleView({
  text,
  setText,
  busyOrRunning,
  agentConfigured,
  runParse,
  selectedCount,
  historyCount,
  favoritesCount,
  setHistoryOpen,
  setKudaOpen,
  setBinOpen,
  busy,
  recentPresets,
}: {
  text: string;
  setText: (v: string) => void;
  busyOrRunning: boolean;
  agentConfigured: boolean;
  runParse: () => void;
  selectedCount: number;
  historyCount: number;
  favoritesCount: number;
  setHistoryOpen: (v: boolean) => void;
  setKudaOpen: (v: boolean) => void;
  setBinOpen: (v: boolean) => void;
  busy: "parse" | "preview" | "execute" | null;
  recentPresets: HistoryItem[];
}) {
  return (
    <AgentShell
      toolbar={agentToolbar(
        agentConfigured,
        selectedCount,
        historyCount,
        favoritesCount,
        setKudaOpen,
        setBinOpen,
        setHistoryOpen,
      )}
    >
      <div className="col-span-3 rounded-2xl bg-white px-3 py-2 shadow-[0_0_0_1px_rgba(0,0,0,.03),0_2px_4px_rgba(0,0,0,.05),0_12px_24px_rgba(0,0,0,.05)]">
        <CommandComposer
          value={text}
          onChange={setText}
          onSubmit={runParse}
          disabled={busyOrRunning}
          busy={busy}
          placeholder="отмени сделки до 300 usdt…"
          presets={recentPresets}
          onPickPreset={setText}
        />
      </div>
    </AgentShell>
  );
}

function ResultsView({
  busyOrRunning,
  busy,
  plan,
  preview,
  summary,
  reset,
  runExecute,
  agentConfigured,
  selectedCount,
  historyCount,
  favoritesCount,
  setHistoryOpen,
  setKudaOpen,
  setBinOpen,
}: {
  busyOrRunning: boolean;
  busy: "parse" | "preview" | "execute" | null;
  plan: AgentPlan | null;
  preview: AgentPreview | null;
  summary: string;
  reset: () => void;
  runExecute: () => void;
  agentConfigured: boolean;
  selectedCount: number;
  historyCount: number;
  favoritesCount: number;
  setHistoryOpen: (v: boolean) => void;
  setKudaOpen: (v: boolean) => void;
  setBinOpen: (v: boolean) => void;
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

  return (
    <AgentShell
      toolbar={agentToolbar(
        agentConfigured,
        selectedCount,
        historyCount,
        favoritesCount,
        setKudaOpen,
        setBinOpen,
        setHistoryOpen,
      )}
    >
      <div className="col-span-3 grid gap-3 sm:grid-cols-2">
        <div className={cn(RESULT_CARD, "col-span-3 p-4 sm:col-span-1")}>
          <h3 className="mb-3 text-sm font-semibold text-neutral-600">
            {matched > 0 ? "Найдено" : "Не найдено"}
          </h3>
          {matched > 0 ? (
            <div className="flex items-end gap-2">
              <span className="text-5xl font-bold leading-none tabular-nums text-emerald-700">
                <CountUp value={matched} />
              </span>
              <span className="pb-1.5 text-base font-semibold text-emerald-600">
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

        <div className={cn(RESULT_CARD, "col-span-3 p-4 sm:col-span-1", accent?.card)}>
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
        <div className={cn(RESULT_CARD, "col-span-3 p-4")}>
          <h3 className="mb-3 text-sm font-semibold text-neutral-600">Сделки</h3>
          <div className="overflow-hidden rounded-xl border border-slate-100">
            <div className="grid grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)_minmax(0,0.9fr)_minmax(0,0.75fr)] gap-2 border-b border-slate-100 bg-white px-3 py-2.5 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
              <span>order</span>
              <span>карта</span>
              <span>сумма</span>
              <span>остаток</span>
            </div>
            <div className="max-h-[min(42vh,320px)] overflow-y-auto bg-white">
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

      <div className="col-span-3 flex flex-wrap items-center gap-2 pt-1">
        <RippleButton
          type="button"
          disabled={busyOrRunning || !plan || matched === 0}
          onClick={runExecute}
          rippleColor="#cbd5e1"
          className={BTN_PRIMARY}
        >
          {busy === "execute" ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Запуск…
            </>
          ) : (
            <>
              Подтвердить и запустить
              <ArrowRight className="size-4" />
            </>
          )}
        </RippleButton>
        <RippleButton
          type="button"
          onClick={reset}
          rippleColor="#cbd5e1"
          className={BTN_SECONDARY}
        >
          Сброс
        </RippleButton>
        <span className="w-full text-xs text-muted-foreground sm:ml-auto sm:w-auto">
          {matched} {dealWord(matched)}
          {summary && req && (
            <>
              {" · "}
              <span className={cn("font-semibold", accent?.label)}>
                {req.action === "redirect" ? "редирект" : "отмена"}
              </span>
            </>
          )}
        </span>
      </div>
    </AgentShell>
  );
}

export function AgentCommandBar() {
  const s = useConsole((st) => st.settings);
  const patch = useConsole((st) => st.patchSettings);
  const agentConfigured = useConsole((st) => st.agentConfigured);
  const running = useConsole((st) => st.running);
  const appendLog = useConsole((st) => st.appendLog);
  const openDialog = useConsole((st) => st.openDialog);
  const clearDeclineResult = useConsole((st) => st.clearDeclineResult);

  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"parse" | "preview" | "execute" | null>(null);
  const [summary, setSummary] = useState("");
  const [plan, setPlan] = useState<AgentPlan | null>(null);
  const [preview, setPreview] = useState<AgentPreview | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [kudaOpen, setKudaOpen] = useState(false);
  const [binOpen, setBinOpen] = useState(false);

  const favorites = useMemo(() => history.filter((h) => h.favorite), [history]);
  const recent = useMemo(() => history.filter((h) => !h.favorite), [history]);
  const recentPresets = useMemo(
    () => [...history].sort((a, b) => b.last_used - a.last_used).slice(0, 3),
    [history],
  );
  const showResults = !!plan && !!preview;
  const selectedCount = TRADERS.filter((t) => s.redirAccounts[t.id]).length;

  const loadHistory = useCallback(async () => {
    try {
      const res = (await serverGet("/api/agent/history?limit=20")) as {
        ok?: boolean;
        items?: HistoryItem[];
      };
      if (res?.items) setHistory(res.items);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const logDebug = (lines: string[] | undefined, usage?: Record<string, unknown>) => {
    const next = [...(lines || [])];
    if (usage?.totalTokenCount != null) {
      next.unshift(
        `tokens: prompt=${String(usage.promptTokenCount ?? "?")} out=${String(usage.candidatesTokenCount ?? "?")} total=${String(usage.totalTokenCount)}`,
      );
    }
    for (const line of next) appendLog(`[AGENT] ${line}`);
  };

  const err = (e: string) => {
    appendLog(`[AGENT] ${e}`);
    void openDialog({ title: "AI команда", body: e, danger: true, alert: true });
  };

  const reset = () => {
    setSummary("");
    setPlan(null);
    setPreview(null);
  };

  const runParse = async (overrideText?: string, closeHistory = false) => {
    const q = (overrideText ?? text).trim();
    if (!q) return;
    setText(q);
    setBusy("parse");
    reset();
    if (closeHistory) setHistoryOpen(false);
    try {
      const ui_context = buildUiContext(s);
      const res = (await serverPost("/api/agent/parse", { text: q, ui_context })) as {
        ok?: boolean;
        error?: string;
        summary?: string;
        plan?: AgentPlan;
        debug?: string[];
        usage?: Record<string, unknown>;
        cached?: boolean;
      };
      if (res?.error) {
        err(res.error);
        return;
      }
      if (!res?.plan) {
        err("Не удалось разобрать команду");
        return;
      }
      setPlan(res.plan);
      setSummary(String(res.summary || ""));
      logDebug(res.debug, res.usage);
      setBusy("preview");
      const prev = (await serverPost("/api/agent/preview", {
        plan: res.plan,
        ui_context,
      })) as AgentPreview;
      if (prev?.error) {
        err(prev.error);
        return;
      }
      if (prev.summary) appendLog(`[AGENT] ${prev.summary}`);
      logDebug(prev.debug);
      setPreview(prev);
      void loadHistory();
    } catch (e) {
      err(String(e));
    } finally {
      setBusy(null);
    }
  };

  const runExecute = async () => {
    if (!plan || running) return;
    const n = Number(preview?.matched ?? 0);
    const action = String(plan.action || "decline");
    const title = action === "redirect" ? "Запустить редирект" : "Запустить отмену";
    const ok = await openDialog({
      title,
      body: `${summary}\n\nНайдено: ${n} сделок.\nЗапустить?`,
      danger: true,
      confirmLabel: action === "redirect" ? "Передать" : "Отменить",
    });
    if (!ok) return;
    setBusy("execute");
    clearDeclineResult();
    try {
      const ui_context = buildUiContext(s);
      const res = (await serverPost("/api/agent/execute", {
        plan,
        ui_context,
        text: text.trim(),
      })) as {
        ok?: boolean;
        error?: string;
      };
      if (res?.error) {
        err(res.error);
        return;
      }
      appendLog(`[AGENT] Запущено: ${summary}`);
      setText("");
      reset();
    } catch (e) {
      err(String(e));
    } finally {
      setBusy(null);
    }
  };

  const clearHistory = async () => {
    const ok = await openDialog({
      title: "Очистить историю AI",
      body: "Удалить недавние команды?\nИзбранные останутся.",
      danger: true,
      confirmLabel: "Очистить",
    });
    if (!ok) return;
    try {
      await serverPost("/api/agent/history/clear");
      await loadHistory();
      appendLog("[AGENT] История очищена (избранные сохранены)");
    } catch (e) {
      err(String(e));
    }
  };

  const removeHistoryItem = async (itemText: string, e: MouseEvent) => {
    e.stopPropagation();
    try {
      await serverPost("/api/agent/history/remove", { text: itemText });
      setHistory((prev) => prev.filter((h) => h.text !== itemText));
    } catch {
      /* ignore */
    }
  };

  const toggleFavorite = async (item: HistoryItem, e: MouseEvent) => {
    e.stopPropagation();
    const next = !item.favorite;
    try {
      await serverPost("/api/agent/history/favorite", {
        text: item.text,
        favorite: next,
      });
      setHistory((prev) =>
        prev.map((h) => (h.text === item.text ? { ...h, favorite: next } : h)),
      );
    } catch {
      /* ignore */
    }
  };

  const busyOrRunning = !!busy || running;
  const historyCount = history.length;

  return (
    <>
      <div className="relative">
        {showResults ? (
          <ResultsView
            busyOrRunning={busyOrRunning}
            busy={busy}
            plan={plan}
            preview={preview}
            summary={summary}
            reset={reset}
            runExecute={() => void runExecute()}
            agentConfigured={agentConfigured}
            selectedCount={selectedCount}
            historyCount={historyCount}
            favoritesCount={favorites.length}
            setHistoryOpen={setHistoryOpen}
            setKudaOpen={setKudaOpen}
            setBinOpen={setBinOpen}
          />
        ) : (
          <IdleView
            text={text}
            setText={setText}
            busyOrRunning={busyOrRunning}
            agentConfigured={agentConfigured}
            runParse={() => void runParse()}
            selectedCount={selectedCount}
            historyCount={historyCount}
            favoritesCount={favorites.length}
            setHistoryOpen={setHistoryOpen}
            setKudaOpen={setKudaOpen}
            setBinOpen={setBinOpen}
            busy={busy}
            recentPresets={recentPresets}
          />
        )}
      </div>

      <BinDirectoryPanel
        open={binOpen}
        onOpenChange={setBinOpen}
        disabled={busyOrRunning}
        onInsert={(t) => {
          setText(t);
          reset();
        }}
      />

      <KudaPanel
        open={kudaOpen}
        onOpenChange={setKudaOpen}
        settings={s}
        patch={patch}
        disabled={busyOrRunning}
      />

      <HistoryPanel
        open={historyOpen}
        onOpenChange={setHistoryOpen}
        favorites={favorites}
        recent={recent}
        disabled={busyOrRunning}
        onRun={(t) => void runParse(t, true)}
        onToggleFavorite={toggleFavorite}
        onRemove={removeHistoryItem}
        onClear={() => void clearHistory()}
      />
    </>
  );
}
