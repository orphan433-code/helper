import { type ReactNode } from "react";
import { BlurFade } from "@/components/ui/blur-fade";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { BentoCard, BentoGrid } from "@/components/ui/bento-grid";
import { RippleButton } from "@/components/ui/ripple-button";
import { api, apiCall } from "@/lib/api";
import {
  BANK_BINS,
  EXTRA_REDIRECT_BINS,
  bankAllBins,
  type BankBinRow,
} from "@/lib/bankBins";
import { TRADERS } from "@/lib/types";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

function selectedBankSummary(bins: string[]): string {
  const parts: string[] = [];
  for (const row of BANK_BINS) {
    const n = bankAllBins(row).filter((b) => bins.includes(b)).length;
    if (n) parts.push(`${row.name} ${n}`);
  }
  for (const extra of EXTRA_REDIRECT_BINS) {
    if (bins.includes(extra)) parts.push(extra);
  }
  return parts.join(" + ");
}

export function DealsView() {
  const s = useConsole((st) => st.settings);
  const patch = useConsole((st) => st.patchSettings);
  const running = useConsole((st) => st.running);
  const jobMode = useConsole((st) => st.jobMode);
  const appendLog = useConsole((st) => st.appendLog);
  const openDialog = useConsole((st) => st.openDialog);
  const clearDeclineResult = useConsole((st) => st.clearDeclineResult);

  const err = (e: string) => {
    appendLog(`[ОШИБКА] ${e}`);
    void openDialog({ title: "Ошибка", body: e, danger: true, alert: true });
  };

  const opsBusy = running && (jobMode === "redirect" || jobMode === "decline");
  const selectedLabels = TRADERS.filter((t) => s.redirAccounts[t.id]).map((t) => t.label);
  const selectedTraders = TRADERS.filter((t) => s.redirAccounts[t.id]).map((t) => t.traderId);

  const extraRedirect = EXTRA_REDIRECT_BINS.filter((b) => s.redirectBinList.includes(b));

  const patchRedirectBins = (next: Record<string, boolean>) => patch({ redirectBins: next });
  const patchDeclineBins = (next: Record<string, boolean>) => patch({ declineBins: next });

  const saveFilters = () => {
    const bins = s.redirectBinList.filter((p) => s.redirectBins[p]);
    return apiCall(
      () =>
        api().save_redirect_filters(
          s.redirSkipBog,
          s.redirVisaOnly,
          s.redirMaxRemaining,
          bins,
        ),
      err,
    );
  };

  const redirect = async (status: string) => {
    if (opsBusy) return;
    if (!selectedTraders.length) {
      await openDialog({
        title: "Редирект",
        body: "Выбери хотя бы один аккаунт",
        alert: true,
      });
      return;
    }
    const maxN = parseInt(String(s.redirMax).trim(), 10);
    if (!Number.isFinite(maxN) || maxN < 1) {
      await openDialog({
        title: "Редирект",
        body: "Укажи количество",
        alert: true,
      });
      return;
    }

    const where = selectedLabels.join(", ");
    const bins = s.redirectBinList.filter((p) => s.redirectBins[p]);
    const bankNote = bins.length ? ` · ${selectedBankSummary(bins)}` : "";
    const ok = await openDialog({
      title: "Передать сделки",
      body: `${maxN} шт. · ${status === "pending" ? "PENDING" : "NEW"} → ${where}${bankNote}`,
      danger: true,
      confirmLabel: "Передать",
    });
    if (!ok) return;

    clearDeclineResult();
    await apiCall(async () => {
      await saveFilters();
      return api().start_redirect(
        selectedTraders,
        maxN,
        s.redirMin || null,
        s.redirMaxAmt || null,
        status,
        s.redirSkipBog,
        s.redirVisaOnly,
        s.redirMaxRemaining,
        bins,
      );
    }, err);
  };

  const declineRun = async () => {
    if (opsBusy) return;
    const bins = s.declineBinList.filter((p) => s.declineBins[p]);
    if (!bins.length) {
      await openDialog({
        title: "Отмена",
        body: "Включи хотя бы один BIN",
        alert: true,
      });
      return;
    }
    const maxN = parseInt(String(s.declineMax).trim(), 10);
    if (!Number.isFinite(maxN) || maxN < 1) {
      await openDialog({
        title: "Отмена",
        body: "Укажи количество (1–50)",
        alert: true,
      });
      return;
    }
    const take = Math.min(50, maxN);
    const amtBits = [
      ...(s.declineMinAmt.trim() ? [`от ${s.declineMinAmt.trim()}`] : []),
      ...(s.declineMaxAmt.trim() ? [`до ${s.declineMaxAmt.trim()}`] : []),
    ];
    const amtNote = amtBits.length ? ` · ${amtBits.join(" ")} USDT` : "";
    const ok = await openDialog({
      title: "Отменить сделки",
      body: `${selectedBankSummary(bins)} · ${take} шт.${amtNote} · сначала меньший остаток времени`,
      danger: true,
      confirmLabel: "Отменить",
    });
    if (!ok) return;
    clearDeclineResult();
    await apiCall(
      () =>
        api().start_decline(
          [...bins],
          false,
          take,
          s.declineMinAmt.trim() || null,
          s.declineMaxAmt.trim() || null,
        ),
      err,
    );
  };

  return (
    <BlurFade delay={0.05} inView>
      <BentoGrid className="lg:grid-rows-[auto]">
        <BentoCard className="col-span-3" name="Редирект">
          <div className="flex flex-col gap-3">
            <div className="space-y-1.5">
              <Label>Куда</Label>
              <div className="grid grid-cols-3 gap-2">
                {TRADERS.map((t) => (
                  <label
                    key={t.id}
                    className="flex cursor-pointer items-center justify-between gap-2 rounded-xl border border-border/80 bg-muted/25 px-3 py-2.5"
                  >
                    <span className="text-sm font-semibold">{t.label}</span>
                    <Switch
                      checked={!!s.redirAccounts[t.id]}
                      disabled={opsBusy}
                      onCheckedChange={(v) =>
                        patch({
                          redirAccounts: { ...s.redirAccounts, [t.id]: v },
                        })
                      }
                    />
                  </label>
                ))}
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Сколько">
                <Input
                  inputMode="numeric"
                  min={1}
                  max={100}
                  value={s.redirMax}
                  placeholder="1–100"
                  disabled={opsBusy}
                  onChange={(e) =>
                    patch({
                      redirMax: e.target.value.replace(/[^\d]/g, "").slice(0, 3),
                    })
                  }
                />
              </Field>
              <Field label="От">
                <Input
                  value={s.redirMin}
                  placeholder="USDT"
                  disabled={opsBusy}
                  onChange={(e) => patch({ redirMin: e.target.value })}
                />
              </Field>
              <Field label="До">
                <Input
                  value={s.redirMaxAmt}
                  placeholder="USDT"
                  disabled={opsBusy}
                  onChange={(e) => patch({ redirMaxAmt: e.target.value })}
                />
              </Field>
            </div>

            <div className="space-y-1.5">
              <Label>Банки и BIN</Label>
              <div className="grid gap-2 sm:grid-cols-2">
                {BANK_BINS.map((row) => (
                  <BankBinGroup
                    key={row.id}
                    bank={row}
                    selected={s.redirectBins}
                    disabled={opsBusy}
                    onChange={patchRedirectBins}
                  />
                ))}
                {extraRedirect.length > 0 && (
                  <ExtraBinGroup
                    bins={extraRedirect}
                    selected={s.redirectBins}
                    disabled={opsBusy}
                    onChange={patchRedirectBins}
                  />
                )}
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                <ToggleRow
                  label="Пропуск BoG"
                  checked={s.redirSkipBog}
                  disabled={opsBusy}
                  onChange={(v) => patch({ redirSkipBog: v })}
                />
                <ToggleRow
                  label="Только Visa"
                  checked={s.redirVisaOnly}
                  disabled={opsBusy}
                  onChange={(v) => patch({ redirVisaOnly: v })}
                />
                <ToggleRow
                  label="Остаток < 1ч"
                  checked={s.redirMaxRemaining}
                  disabled={opsBusy}
                  onChange={(v) => patch({ redirMaxRemaining: v })}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                Банк вкл — все его BIN. BIN вкл — только эти карты. Все выкл — любые.
              </p>
            </div>

            <div className="flex flex-wrap gap-2 pt-1">
              <RippleButton
                disabled={opsBusy}
                onClick={() => void redirect("new")}
                className="flex-1 border-primary bg-primary text-primary-foreground hover:brightness-105"
              >
                NEW
              </RippleButton>
              <RippleButton
                disabled={opsBusy}
                onClick={() => void redirect("pending")}
                rippleColor="#cbd5e1"
                className="flex-1 border-border bg-secondary text-secondary-foreground hover:bg-slate-200/80"
              >
                PENDING
              </RippleButton>
            </div>
          </div>
        </BentoCard>

        <BentoCard className="col-span-3" name="Отмена">
          <div className="flex flex-col gap-3">
            <div className="space-y-1.5">
              <Label>Банки и BIN</Label>
              <div className="grid gap-2 sm:grid-cols-2">
                {BANK_BINS.map((row) => (
                  <BankBinGroup
                    key={row.id}
                    bank={row}
                    selected={s.declineBins}
                    disabled={opsBusy}
                    onChange={patchDeclineBins}
                  />
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                TBC — по BIN карт, не по имени банка. Банк вкл — все его номера.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Сколько">
                <Input
                  inputMode="numeric"
                  min={1}
                  max={50}
                  value={s.declineMax}
                  placeholder="1–50"
                  disabled={opsBusy}
                  onChange={(e) =>
                    patch({
                      declineMax: e.target.value.replace(/[^\d]/g, "").slice(0, 2),
                    })
                  }
                />
              </Field>
              <Field label="От">
                <Input
                  value={s.declineMinAmt}
                  placeholder="USDT"
                  disabled={opsBusy}
                  onChange={(e) => patch({ declineMinAmt: e.target.value })}
                />
              </Field>
              <Field label="До">
                <Input
                  value={s.declineMaxAmt}
                  placeholder="USDT"
                  disabled={opsBusy}
                  onChange={(e) => patch({ declineMaxAmt: e.target.value })}
                />
              </Field>
            </div>
            <RippleButton
              disabled={opsBusy}
              onClick={() => void declineRun()}
              className="w-full border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
              rippleColor="#fecaca"
            >
              Отменить
            </RippleButton>
          </div>
        </BentoCard>
      </BentoGrid>
    </BlurFade>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function ToggleRow({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-2 rounded-xl border border-border/80 bg-muted/25 px-3 py-2.5">
      <span className="text-sm font-semibold text-foreground">{label}</span>
      <Switch checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </label>
  );
}

function BinChip({
  bin,
  checked,
  disabled,
  onToggle,
}: {
  bin: string;
  checked: boolean;
  disabled: boolean;
  onToggle: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-pressed={checked}
      onClick={() => onToggle(!checked)}
      className={cn(
        "rounded-md px-1.5 py-0.5 font-mono text-[11px] tabular-nums transition",
        checked
          ? "bg-slate-900 text-white"
          : "bg-muted text-slate-700 hover:bg-slate-200",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      {bin}
    </button>
  );
}

function BankBinGroup({
  bank,
  selected,
  disabled,
  onChange,
}: {
  bank: BankBinRow;
  selected: Record<string, boolean>;
  disabled: boolean;
  onChange: (next: Record<string, boolean>) => void;
}) {
  const bins = bankAllBins(bank);
  const onCount = bins.filter((b) => selected[b]).length;

  const setMany = (codes: string[], v: boolean) => {
    const next = { ...selected };
    for (const code of codes) next[code] = v;
    onChange(next);
  };

  return (
    <div className="rounded-xl border border-border/80 bg-muted/20 p-2.5">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{bank.name}</p>
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            {onCount}/{bins.length} BIN
          </p>
        </div>
        <TriSwitch
          onCount={onCount}
          total={bins.length}
          disabled={disabled}
          onToggleAll={(v) => setMany(bins, v)}
        />
      </div>
      {bank.visa.length > 0 && (
        <BinLane
          label="Visa"
          bins={bank.visa}
          selected={selected}
          disabled={disabled}
          onToggle={(bin, v) => onChange({ ...selected, [bin]: v })}
        />
      )}
      {bank.mastercard.length > 0 && (
        <BinLane
          label="MC"
          bins={bank.mastercard}
          selected={selected}
          disabled={disabled}
          onToggle={(bin, v) => onChange({ ...selected, [bin]: v })}
        />
      )}
    </div>
  );
}

function ExtraBinGroup({
  bins,
  selected,
  disabled,
  onChange,
}: {
  bins: string[];
  selected: Record<string, boolean>;
  disabled: boolean;
  onChange: (next: Record<string, boolean>) => void;
}) {
  const onCount = bins.filter((b) => selected[b]).length;
  return (
    <div className="rounded-xl border border-border/80 bg-muted/20 p-2.5">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-sm font-semibold">Другие</p>
        <TriSwitch
          onCount={onCount}
          total={bins.length}
          disabled={disabled}
          onToggleAll={(v) => {
            const next = { ...selected };
            for (const code of bins) next[code] = v;
            onChange(next);
          }}
        />
      </div>
      <BinLane
        label="BIN"
        bins={bins}
        selected={selected}
        disabled={disabled}
        onToggle={(bin, v) => onChange({ ...selected, [bin]: v })}
      />
    </div>
  );
}

function TriSwitch({
  onCount,
  total,
  disabled,
  onToggleAll,
}: {
  onCount: number;
  total: number;
  disabled: boolean;
  onToggleAll: (allOn: boolean) => void;
}) {
  const allOn = total > 0 && onCount === total;
  const mixed = onCount > 0 && !allOn;

  return (
    <button
      type="button"
      role="switch"
      aria-checked={mixed ? "mixed" : allOn}
      aria-label={mixed ? "Часть BIN" : allOn ? "Все BIN" : "Нет BIN"}
      disabled={disabled}
      onClick={() => onToggleAll(!allOn && !mixed)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border shadow-sm transition",
        allOn && "border-primary bg-primary",
        mixed && "border-slate-800 bg-slate-800",
        !allOn && !mixed && "border-slate-300 bg-white",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <span
        className={cn(
          "pointer-events-none flex size-5 items-center justify-center rounded-full bg-white shadow transition-transform",
          allOn && "translate-x-[22px]",
          mixed && "translate-x-[11px]",
          !allOn && !mixed && "translate-x-0.5",
        )}
      >
        {mixed && <span className="h-0.5 w-2.5 rounded-full bg-slate-800" />}
      </span>
    </button>
  );
}

function BinLane({
  label,
  bins,
  selected,
  disabled,
  onToggle,
}: {
  label: string;
  bins: string[];
  selected: Record<string, boolean>;
  disabled: boolean;
  onToggle: (bin: string, v: boolean) => void;
}) {
  return (
    <div className="mt-1.5">
      <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <div className="flex flex-wrap gap-1">
        {bins.map((bin) => (
          <BinChip
            key={bin}
            bin={bin}
            checked={!!selected[bin]}
            disabled={disabled}
            onToggle={(v) => onToggle(bin, v)}
          />
        ))}
      </div>
    </div>
  );
}
