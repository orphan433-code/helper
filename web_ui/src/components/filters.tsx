import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

export function ToggleRow({
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

export function FilterChip({
  label,
  active,
  disabled,
  onClick,
  tone = "default",
}: {
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  tone?: "default" | "warn" | "danger";
}) {
  return (
    <button
      type="button"
      disabled={disabled || !onClick}
      onClick={onClick}
      className={cn(
        "cursor-pointer rounded-full border px-2.5 py-1 text-xs font-semibold transition-all",
        active && tone === "default" &&
          "border-primary bg-primary text-primary-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.18),0_1px_2px_rgba(26,35,50,0.28)]",
        active && tone === "warn" && "border-amber-500/20 bg-amber-500/10 text-amber-800",
        active && tone === "danger" && "border-danger/25 bg-danger-soft text-danger",
        !active &&
          "border-border/50 bg-background/70 text-foreground/70 shadow-sm hover:bg-foreground/[0.06] hover:text-foreground",
        (disabled || !onClick) && "cursor-default",
        disabled && "opacity-50",
      )}
    >
      {label}
    </button>
  );
}

export function FilterChipRow({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-1.5">{children}</div>;
}

export function FilterBar({
  facts,
  onEdit,
  disabled,
}: {
  facts: { label: string; value: string }[];
  onEdit: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onEdit}
      className={cn(
        "flex w-full cursor-pointer items-center gap-3 rounded-xl border border-foreground/[0.08] bg-white/90 px-3 py-2.5 text-left shadow-[0_1px_2px_rgba(26,35,50,0.06)] transition-colors hover:bg-white",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2.5 gap-y-1">
        {facts.map((fact, i) => (
          <span key={fact.label} className="flex min-w-0 items-baseline gap-1.5">
            {i > 0 && (
              <span className="hidden text-foreground/20 sm:inline" aria-hidden>
                ·
              </span>
            )}
            <span className="text-[11px] font-medium text-muted-foreground">{fact.label}</span>
            <span className="truncate text-sm font-semibold text-foreground">{fact.value}</span>
          </span>
        ))}
      </div>
      <span className="shrink-0 text-xs font-semibold text-foreground/55">изменить</span>
    </button>
  );
}

export function FilterSection({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div>
        <p className="text-sm font-semibold text-foreground">{label}</p>
        {hint && <p className="text-[11px] leading-snug text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  disabled,
  onChange,
}: {
  value: T;
  options: { id: T; label: string; hint?: string }[];
  disabled?: boolean;
  onChange: (id: T) => void;
}) {
  return (
    <div
      role="radiogroup"
      className="grid gap-1 rounded-2xl border border-foreground/[0.08] bg-foreground/[0.07] p-1"
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      {options.map((opt) => {
        const on = value === opt.id;
        return (
          <button
            key={opt.id}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            onClick={() => onChange(opt.id)}
            className={cn(
              "cursor-pointer rounded-xl px-3 py-2.5 text-sm font-semibold transition-all duration-150",
              on
                ? "bg-white text-foreground shadow-[0_1px_2px_rgba(26,35,50,0.14)]"
                : "text-foreground/45 hover:bg-white/45 hover:text-foreground/80",
              disabled && "cursor-not-allowed opacity-50",
            )}
          >
            {opt.label}
            {opt.hint ? (
              <span className={cn("font-medium", on ? "text-foreground/50" : "opacity-80")}>
                {opt.hint}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export function CollapsibleBlock({
  open,
  onOpenChange,
  title,
  hint,
  disabled,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  hint?: string;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border/80 bg-muted/15">
      <button
        type="button"
        disabled={disabled}
        onClick={() => onOpenChange(!open)}
        className={cn(
          "flex w-full cursor-pointer items-center gap-2 px-3 py-2.5 text-left",
          disabled && "cursor-not-allowed opacity-50",
        )}
      >
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-foreground">{title}</span>
          {hint && (
            <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">{hint}</span>
          )}
        </span>
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && <div className="space-y-2 border-t border-border/60 p-2.5">{children}</div>}
    </div>
  );
}
