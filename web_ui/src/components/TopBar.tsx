import { IDLE_STATUS } from "@/lib/types";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

export function TopBar() {
  const statusText = useConsole((s) => s.statusText);
  const statusKind = useConsole((s) => s.statusKind);
  const appVersion = useConsole((s) => s.appVersion);

  const idle =
    statusKind === "idle" &&
    (!statusText || statusText === IDLE_STATUS || statusText === "Можно запускать");
  const showStatus = !idle && !!statusText.trim();

  return (
    <header className="mb-4 flex items-center justify-between gap-3 px-0.5">
      <div className="flex min-w-0 items-baseline gap-2">
        <h1 className="text-lg font-semibold tracking-tight text-foreground">TJS</h1>
        <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-foreground/45">
          Operator
        </span>
      </div>

      <div className="flex min-w-0 items-center gap-3">
        {showStatus && (
          <p
            className={cn(
              "flex min-w-0 max-w-[min(28rem,52vw)] items-center gap-1.5 text-[13px] leading-none",
              statusKind === "error" && "text-danger",
              statusKind === "waiting" && "text-amber-700",
              statusKind === "running" && "text-foreground",
              statusKind === "success" && "text-ok",
              statusKind === "idle" && "text-foreground/55",
            )}
            role="status"
          >
            <span
              className={cn(
                "size-1.5 shrink-0 rounded-full",
                statusKind === "idle" && "bg-foreground/35",
                statusKind === "running" && "bg-primary",
                statusKind === "waiting" && "bg-amber-500",
                statusKind === "success" && "bg-ok",
                statusKind === "error" && "bg-danger",
              )}
            />
            <span className="min-w-0 truncate font-medium">{statusText}</span>
          </p>
        )}
        <span className="shrink-0 font-mono text-[11px] text-foreground/45">v{appVersion}</span>
      </div>
    </header>
  );
}
