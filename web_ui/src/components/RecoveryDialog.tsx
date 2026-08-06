import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
    void openDialog({ title: "Ошибка", body: e, danger: true });
  };

  return (
    <Dialog
      open={recovery.open}
      onOpenChange={(open) => {
        if (!open) hideRecoveryPrompt();
      }}
    >
      <DialogContent className="border-red-200">
        <DialogHeader>
          <div className="mb-1 inline-flex w-fit rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-red-700">
            Требуется действие
          </div>
          <DialogTitle>{recovery.message || "Произошла ошибка"}</DialogTitle>
          <DialogDescription>{recovery.detail}</DialogDescription>
        </DialogHeader>

        {recovery.deal && (
          <div className="rounded-xl border border-border bg-muted/30 p-3">
            <div className="mb-2 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
              Сделка
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <Cell label="Номер" value={recovery.deal.index || "—"} />
              <Cell label="Карта" value={recovery.deal.card || "—"} />
              <div className="col-span-2">
                <Cell label="Получатель" value={recovery.deal.holder || "—"} mono={false} />
              </div>
              <Cell label="Сумма перевода" value={recovery.deal.amount_tjs || "—"} />
              <Cell label="К получению" value={recovery.deal.amount_target || "—"} />
            </div>
          </div>
        )}

        {recovery.hint && (
          <p className="text-sm text-muted-foreground">{recovery.hint}</p>
        )}

        <DialogFooter>
          {recovery.allowRetry && (
            <Button
              onClick={() =>
                void apiCall(() => api().recovery_retry(), err).then(() => hideRecoveryPrompt())
              }
            >
              Повторить шаг
            </Button>
          )}
          <Button
            variant="warn"
            onClick={() =>
              void apiCall(() => api().recovery_continue(), err).then(() => hideRecoveryPrompt())
            }
          >
            {recovery.continueLabel}
          </Button>
          <Button
            variant="danger"
            onClick={() =>
              void apiCall(() => api().recovery_exit(), err).then(() => hideRecoveryPrompt())
            }
          >
            Остановить всё
          </Button>
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
      <div className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className={mono ? "font-mono font-semibold" : "font-semibold"}>{value}</div>
    </div>
  );
}
