import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTone,
} from "@/components/ui/dialog";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

export function ResultOverlay() {
  const open = useConsole((s) => s.declineResultOpen);
  const panel = useConsole((s) => s.decline);
  const dismiss = useConsole((s) => s.dismissDeclineResult);

  const shown = open && panel.done;
  const failed = panel.hasErrors;
  const body = panel.message || panel.success || "";

  return (
    <Dialog open={shown} onOpenChange={(next) => !next && dismiss()}>
      <DialogContent className="max-w-xl">
        <div className="flex items-start gap-3.5">
          <DialogTone tone={failed ? "warn" : "ok"} />
          <DialogHeader className="min-w-0 flex-1 pt-0.5">
            <DialogTitle>{panel.title || "Готово"}</DialogTitle>
            <DialogDescription className={body ? "mt-1" : "sr-only"}>
              {body || panel.summary || "Готово"}
            </DialogDescription>
          </DialogHeader>
        </div>

        {panel.summary && (
          <p className="mt-3 font-mono text-xs text-slate-400">{panel.summary}</p>
        )}

        {!!panel.deals.length && (
          <ul className="mt-3 max-h-72 space-y-1.5 overflow-auto pr-0.5">
            {panel.deals.map((d, i) => {
              const bad = !!(d.error || d.ok === false);
              return (
                <li
                  key={d.id || d.order_id || i}
                  className={cn(
                    "rounded-xl border px-3 py-2 text-sm",
                    bad ? "border-amber-200 bg-amber-50/60" : "border-slate-200 bg-slate-50/80",
                  )}
                >
                  <div className="flex justify-between gap-2 font-medium">
                    <span className="truncate">
                      {d.holder || d.order_id || `#${d.index ?? i + 1}`}
                    </span>
                    <span className="shrink-0 font-mono text-slate-600">
                      {d.amount || "—"}
                    </span>
                  </div>
                  <div className="mt-0.5 text-xs text-slate-500">
                    {[d.card, d.order_id].filter(Boolean).join(" · ") || "—"}
                  </div>
                  {d.error && <div className="mt-1 text-xs text-red-600">{d.error}</div>}
                </li>
              );
            })}
          </ul>
        )}

        {panel.errorDetail && (
          <pre className="mt-3 max-h-32 overflow-auto whitespace-pre-wrap rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700">
            {panel.errorDetail}
          </pre>
        )}

        <DialogFooter>
          <Button className="w-full shadow-none" onClick={dismiss}>
            OK
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
