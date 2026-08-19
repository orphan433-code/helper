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
import { api, apiCall } from "@/lib/api";
import { useConsole } from "@/store/console";

export function RecoveryDialog() {
  const recovery = useConsole((s) => s.recovery);
  const hideRecoveryPrompt = useConsole((s) => s.hideRecoveryPrompt);
  const appendLog = useConsole((s) => s.appendLog);
  const openDialog = useConsole((s) => s.openDialog);

  const err = (e: string) => {
    appendLog(`[ОШИБКА] ${e}`);
    void openDialog({ title: "Ошибка", body: e, danger: true, alert: true });
  };

  return (
    <Dialog
      open={recovery.open}
      onOpenChange={(open) => {
        if (!open) hideRecoveryPrompt();
      }}
    >
      <DialogContent className="max-w-lg" showClose={false}>
        <div className="flex items-start gap-3.5">
          <DialogTone tone="danger" />
          <DialogHeader className="min-w-0 flex-1">
            <DialogTitle>{recovery.message || "Ошибка"}</DialogTitle>
            {recovery.detail ? (
              <DialogDescription className="mt-1">{recovery.detail}</DialogDescription>
            ) : (
              <DialogDescription className="sr-only">Ошибка сделки</DialogDescription>
            )}
          </DialogHeader>
        </div>

        {recovery.deal && (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/80 p-3">
            <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
              <Cell label="№" value={recovery.deal.index || "—"} />
              <Cell label="Карта" value={recovery.deal.card || "—"} />
              <div className="col-span-2">
                <Cell label="Получатель" value={recovery.deal.holder || "—"} mono={false} />
              </div>
              <Cell label="Перевод" value={recovery.deal.amount_tjs || "—"} />
              <Cell label="К получению" value={recovery.deal.amount_target || "—"} />
            </div>
          </div>
        )}

        {recovery.hint && (
          <p className="mt-3 text-sm leading-snug text-slate-500">{recovery.hint}</p>
        )}

        <DialogFooter className="grid grid-cols-2 sm:grid-cols-3">
          <Button
            variant="danger"
            className="w-full"
            onClick={() =>
              void apiCall(() => api().recovery_exit(), err).then(() => hideRecoveryPrompt())
            }
          >
            Стоп
          </Button>
          <Button
            variant="outline"
            className="w-full"
            onClick={() =>
              void apiCall(() => api().recovery_continue(), err).then(() => hideRecoveryPrompt())
            }
          >
            {recovery.continueLabel}
          </Button>
          {recovery.allowRetry && (
            <Button
              className="w-full shadow-none"
              onClick={() =>
                void apiCall(() => api().recovery_retry(), err).then(() => hideRecoveryPrompt())
              }
            >
              Повтор
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Cell({
  label,
  value,
  mono = true,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
        {label}
      </div>
      <div className={mono ? "font-mono text-sm font-semibold" : "text-sm font-semibold"}>
        {value}
      </div>
    </div>
  );
}
