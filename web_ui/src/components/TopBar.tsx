import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

export function TopBar() {
  const statusText = useConsole((s) => s.statusText);
  const statusKind = useConsole((s) => s.statusKind);
  const statusLabel = useConsole((s) => s.statusLabel);
  const appVersion = useConsole((s) => s.appVersion);
  const view = useConsole((s) => s.view);

  return (
    <header className="mb-5 space-y-2 px-0.5">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <h1 className="text-lg font-bold tracking-tight text-slate-900">TJS</h1>
          <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-slate-400">
            Operator
          </span>
        </div>
        <span className="font-mono text-[11px] text-slate-400">v{appVersion}</span>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-slate-200/80 pb-3">
        {view === "run" ? (
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">
            Телефон → вход → переводы → чеки
          </p>
        ) : (
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">
            {view === "deals" ? "Операции" : "Журнал"}
          </p>
        )}

        <p
          className={cn(
            "flex min-w-0 max-w-full items-center gap-1.5 text-[13px] leading-none",
            statusKind === "error" && "text-red-600",
            statusKind === "waiting" && "text-amber-700",
            statusKind === "running" && "text-slate-800",
            (statusKind === "idle" || statusKind === "success") && "text-slate-500",
          )}
          role="status"
        >
          <span
            className={cn(
              "size-1.5 shrink-0 rounded-full",
              statusKind === "idle" && "bg-slate-400",
              statusKind === "running" && "bg-slate-800",
              statusKind === "waiting" && "bg-amber-500",
              statusKind === "success" && "bg-slate-600",
              statusKind === "error" && "bg-red-500",
            )}
          />
          <span className="shrink-0 font-medium">{statusLabel}</span>
          <span className="text-slate-300">·</span>
          <span className="min-w-0 truncate font-normal">{statusText}</span>
        </p>
      </div>
    </header>
  );
}
