import {
  BANK_BINS,
  bankAllBins,
  type BankBinRow,
} from "@/lib/bankBins";
import { cn } from "@/lib/utils";

const SHORT: Record<string, string> = {
  bog: "BOG",
  basis: "Basis",
  liberty: "Liberty",
  tbc: "TBC",
};

export function bankShortName(bank: BankBinRow): string {
  return SHORT[bank.id] || bank.name;
}

export function selectedBinCount(
  selected: Record<string, boolean>,
  bins: string[],
): number {
  return bins.filter((b) => selected[b]).length;
}

export function bankFilterHint(
  selected: Record<string, boolean>,
  bins: string[],
  extra: string[] = [],
): string {
  const all = [...bins, ...extra];
  const on = all.filter((b) => selected[b]);
  if (!on.length) return "любые карты";
  const names = BANK_BINS.filter((row) =>
    bankAllBins(row).some((b) => selected[b]),
  ).map(bankShortName);
  const extraOn = extra.filter((b) => selected[b]);
  if (extraOn.length) names.push("прочие");
  const unique = [...new Set(names)];
  return `${unique.join(", ")} · ${on.length} BIN`;
}

export function BinPicker({
  selected,
  disabled,
  extra,
  extraName = "Прочие",
  onChange,
}: {
  selected: Record<string, boolean>;
  disabled: boolean;
  extra?: string[];
  extraName?: string;
  onChange: (next: Record<string, boolean>) => void;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {BANK_BINS.map((row) => (
        <BankBinGroup
          key={row.id}
          bank={row}
          selected={selected}
          disabled={disabled}
          onChange={onChange}
        />
      ))}
      {extra && extra.length > 0 && (
        <ExtraBinGroup
          name={extraName}
          bins={extra}
          selected={selected}
          disabled={disabled}
          onChange={onChange}
        />
      )}
    </div>
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
        "cursor-pointer rounded-md px-1.5 py-0.5 font-mono text-[11px] tabular-nums transition",
        checked
          ? "bg-primary text-primary-foreground"
          : "bg-background/60 text-foreground/80 hover:bg-foreground/[0.06]",
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
  const onCount = selectedBinCount(selected, bins);

  const setMany = (codes: string[], v: boolean) => {
    const next = { ...selected };
    for (const code of codes) next[code] = v;
    onChange(next);
  };

  return (
    <div className="rounded-xl border border-border/40 bg-background/50 p-2.5 backdrop-blur-xl">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{bankShortName(bank)}</p>
          <p className="text-[10px] font-medium text-muted-foreground">
            {onCount}/{bins.length}
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
  name,
  bins,
  selected,
  disabled,
  onChange,
}: {
  name: string;
  bins: string[];
  selected: Record<string, boolean>;
  disabled: boolean;
  onChange: (next: Record<string, boolean>) => void;
}) {
  const onCount = selectedBinCount(selected, bins);
  return (
    <div className="rounded-xl border border-border/40 bg-background/50 p-2.5 backdrop-blur-xl">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-sm font-semibold">{name}</p>
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
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border shadow-sm transition",
        allOn && "border-primary bg-primary",
        mixed && "border-primary/70 bg-primary/70",
        !allOn && !mixed && "border-border/50 bg-background/70",
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
        {mixed && <span className="h-0.5 w-2.5 rounded-full bg-primary" />}
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
