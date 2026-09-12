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

function lineValue(prompt: string, prefix: string): string {
  const hit = prompt
    .split("\n")
    .map((s) => s.trim())
    .find((s) => s.startsWith(prefix));
  if (!hit) return "";
  return hit.slice(prefix.length).trim();
}

export function RatesConfirmDialog() {
  const waiting = useConsole((s) => s.waitingConfirm);
  const mode = useConsole((s) => s.confirmMode);
  const prompt = useConsole((s) => s.confirmPrompt);
  const appendLog = useConsole((s) => s.appendLog);
  const openDialog = useConsole((s) => s.openDialog);
  const hideConfirmPrompt = useConsole((s) => s.hideConfirmPrompt);
  const open = waiting && mode === "eze_rates";

  const eurSell = lineValue(prompt, "EUR продажа");
  const usdSell = lineValue(prompt, "USD продажа");
  const eurBuy = lineValue(prompt, "EUR покупка");
  const usdBuy = lineValue(prompt, "USD покупка");

  const err = (e: string) => {
    appendLog(`[ОШИБКА] ${e}`);
    void openDialog({ title: "Ошибка", body: e, danger: true, alert: true });
  };

  return (
    <Dialog open={open} onOpenChange={() => undefined}>
      <DialogContent className="max-w-md" showClose={false}>
        <div className="flex items-start gap-3.5">
          <DialogTone tone="info" />
          <DialogHeader className="min-w-0 flex-1">
            <DialogTitle>Курс Activ</DialogTitle>
            <DialogDescription className="mt-1">
              Нижнее EUR — продажа, в TJS. Проверь.
            </DialogDescription>
          </DialogHeader>
        </div>

        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/80 p-3">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            В банк · 1 EUR
          </div>
          <div className="mt-0.5 font-mono text-3xl font-bold tracking-tight">
            {eurSell || "—"} <span className="text-base font-semibold text-slate-500">TJS</span>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                USD продажа
              </div>
              <div className="font-mono font-semibold">{usdSell || "—"} TJS</div>
            </div>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                Покупка
              </div>
              <div className="font-mono text-slate-600">
                EUR {eurBuy || "—"} / USD {usdBuy || "—"}
              </div>
            </div>
          </div>
        </div>

        <DialogFooter className="grid grid-cols-2">
          <Button
            variant="outline"
            className="w-full"
            onClick={() => {
              hideConfirmPrompt();
              void apiCall(() => api().stop_job(), err);
            }}
          >
            Стоп
          </Button>
          <Button
            className="w-full shadow-none"
            onClick={() => {
              hideConfirmPrompt();
              void apiCall(() => api().confirm("receipts"), err);
            }}
          >
            Подтвердить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DryStopDialog() {
  const waiting = useConsole((s) => s.waitingConfirm);
  const mode = useConsole((s) => s.confirmMode);
  const prompt = useConsole((s) => s.confirmPrompt);
  const appendLog = useConsole((s) => s.appendLog);
  const openDialog = useConsole((s) => s.openDialog);
  const hideConfirmPrompt = useConsole((s) => s.hideConfirmPrompt);
  const open = waiting && mode === "dry_stop";

  const err = (e: string) => {
    appendLog(`[ОШИБКА] ${e}`);
    void openDialog({ title: "Ошибка", body: e, danger: true, alert: true });
  };

  return (
    <Dialog open={open} onOpenChange={() => undefined}>
      <DialogContent className="max-w-md" showClose={false}>
        <div className="flex items-start gap-3.5">
          <DialogTone tone="ok" />
          <DialogHeader className="min-w-0 flex-1">
            <DialogTitle>Тест: стоп до кода</DialogTitle>
            <DialogDescription className="mt-1 whitespace-pre-line">
              {prompt ||
                "Форма и сверка ок. Оплату и SMS не жмём. Проверь экран на телефоне."}
            </DialogDescription>
          </DialogHeader>
        </div>
        <DialogFooter>
          <Button
            className="w-full shadow-none"
            onClick={() => {
              hideConfirmPrompt();
              void apiCall(() => api().confirm("receipts"), err);
            }}
          >
            Ок
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
