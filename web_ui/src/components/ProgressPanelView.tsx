import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, apiCall } from "@/lib/api";
import type { ProgressPanel } from "@/lib/types";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

export function ProgressPanelView({ panel }: { panel: ProgressPanel }) {
  const appendLog = useConsole((s) => s.appendLog);
  if (!panel.visible) return null;

  return (
    <div
      className={cn(
        "mt-3 rounded-xl border bg-muted/20 p-3",
        panel.processing && "border-slate-300",
        panel.done && "border-slate-300",
        panel.hasErrors && "border-amber-200",
      )}
    >
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <div className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
          {panel.title}
        </div>
        <div className="font-mono text-xs text-slate-600">{panel.summary}</div>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div
          className={cn(
            "h-full rounded-full bg-primary transition-all",
            panel.processing && !panel.done && "w-1/3 animate-pulse",
            panel.done && "w-full",
          )}
        />
      </div>
      {panel.message && (
        <p className="mt-2 text-sm text-muted-foreground">{panel.message}</p>
      )}
      {panel.deals.length > 0 && (
        <ul className="mt-2 max-h-64 space-y-1.5 overflow-auto">
          {panel.deals.map((d) => (
            <li
              key={d.id}
              className={cn(
                "rounded-lg border border-border bg-white px-2.5 py-2 text-xs",
                d.active && "border-slate-300 bg-slate-50",
              )}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-semibold">
                  <span className="mr-2 font-mono text-muted-foreground">#{d.index}</span>
                  {d.holder || "—"}
                </span>
                <span className="font-mono text-slate-700">{d.amount}</span>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-muted-foreground">
                {d.card && <span className="font-mono">{d.card}</span>}
                {d.status && <span>{d.status}</span>}
                {d.has_shot && <Badge variant="secondary">shot</Badge>}
                {d.has_video && <Badge variant="success">video</Badge>}
              </div>
              {d.order_id && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      void apiCall(() => api().retry_completion_deal(d.order_id!), (e) =>
                        appendLog(`[ОШИБКА] ${e}`),
                      )
                    }
                  >
                    Retry
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      void apiCall(() => api().rescan_completion_deal(d.order_id!), (e) =>
                        appendLog(`[ОШИБКА] ${e}`),
                      )
                    }
                  >
                    Rescan
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() =>
                      void apiCall(() => api().cancel_completion_deal(d.order_id!), (e) =>
                        appendLog(`[ОШИБКА] ${e}`),
                      )
                    }
                  >
                    Cancel
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {panel.errorDetail && (
        <pre className="mt-2 whitespace-pre-wrap rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">
          {panel.errorDetail}
        </pre>
      )}
      {panel.success && (
        <div
          className={cn(
            "mt-2 rounded-lg border px-3 py-2 text-sm font-semibold",
            panel.hasErrors
              ? "border-amber-200 bg-amber-50 text-amber-800"
              : "border-emerald-200 bg-emerald-50 text-emerald-800",
          )}
        >
          {panel.success}
        </div>
      )}
    </div>
  );
}
