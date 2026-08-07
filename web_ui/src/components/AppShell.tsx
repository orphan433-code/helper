import { useState } from "react";
import {
  Download,
  FileText,
  LayoutDashboard,
  ListOrdered,
  Loader2,
  Power,
  RotateCcw,
  Square,
} from "lucide-react";
import { TopBar } from "@/components/TopBar";
import { RunView } from "@/components/RunView";
import { DealsView } from "@/components/DealsView";
import { LogView } from "@/components/LogView";
import { RecoveryDialog } from "@/components/RecoveryDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { LightRays } from "@/components/ui/light-rays";
import { api, apiCall, serverPost } from "@/lib/api";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

export function AppShell() {
  const view = useConsole((s) => s.view);
  const setView = useConsole((s) => s.setView);
  const running = useConsole((s) => s.running);
  const appendLog = useConsole((s) => s.appendLog);
  const setStatus = useConsole((s) => s.setStatus);
  const applyState = useConsole((s) => s.applyState);
  const openDialog = useConsole((s) => s.openDialog);
  const clearCancelAlerts = useConsole((s) => s.clearCancelAlerts);
  const [updateBusy, setUpdateBusy] = useState(false);

  const stop = () =>
    apiCall(() => api().stop_job(), (e) => {
      appendLog(`[ОШИБКА] ${e}`);
      void openDialog({ title: "Ошибка", body: e, danger: true, alert: true });
    });

  const restart = async () => {
    clearCancelAlerts();
    appendLog("\n[SERVER] Перезапуск движка…\n");
    try {
      const r = (await serverPost("/api/server/restart")) as {
        ok?: boolean;
        error?: string;
      };
      if (r?.ok === false && r.error) {
        appendLog(`[SERVER] Ошибка: ${r.error}\n`);
        return;
      }
      appendLog("[SERVER] Перезапущено\n");
      applyState(await api().get_state());
      setStatus("Перезапущено — можно работать", "idle");
    } catch (err) {
      appendLog(`[SERVER] ${err}`);
    }
  };

  const shutdown = async () => {
    const ok = await openDialog({
      title: "Выключение",
      body: "Выключить TJS полностью?\nСервер остановится, страница перестанет отвечать.",
      danger: true,
    });
    if (!ok) return;
    appendLog("\n[SERVER] Выключение…\n");
    setStatus("Выключение…", "idle");
    try {
      await serverPost("/api/server/shutdown");
    } catch {
      /* expected */
    }
    window.setTimeout(
      () => setStatus("Сервер выключен — запусти start.sh снова", "error"),
      600,
    );
  };

  const update = async () => {
    if (updateBusy) return;
    if (running) {
      await openDialog({
        title: "Обновление",
        body: "Сначала останови текущую задачу (Стоп), потом обновляй.",
        danger: true,
        alert: true,
      });
      return;
    }
    const ok = await openDialog({
      title: "Обновить код",
      body:
        "Скачать последнюю версию с GitHub?\nconfig.yaml и .venv не затираются.\nПосле обновления нажми ↻ перезапуск.",
    });
    if (!ok) return;

    setUpdateBusy(true);
    setStatus("Обновляю код…", "running");
    appendLog("\n[UPDATE] Скачиваю обновление…\n");
    try {
      const r = await api().apply_app_update();
      if (r && typeof r.error === "string" && r.error) {
        appendLog(`[UPDATE] ${r.error}\n`);
        setStatus("Ошибка обновления", "error");
        await openDialog({
          title: "Обновление не удалось",
          body: String(r.error),
          danger: true,
          alert: true,
        });
        return;
      }
      const msg = String(
        r.message || "Обновление готово. Перезапусти сервер (↻).",
      );
      appendLog(`[UPDATE] ${msg}\n`);
      setStatus("Обновление готово — нажми ↻", "success");
      try {
        applyState(await api().get_state());
      } catch {
        /* ignore */
      }
      await openDialog({
        title: "Успешно",
        body: msg,
        alert: true,
      });
    } catch (e) {
      const msg = String(e);
      appendLog(`[UPDATE] ${msg}\n`);
      setStatus("Ошибка обновления", "error");
      await openDialog({
        title: "Обновление не удалось",
        body: msg,
        danger: true,
        alert: true,
      });
    } finally {
      setUpdateBusy(false);
    }
  };

  const nav = [
    { id: "run" as const, label: "Запуск", Icon: LayoutDashboard },
    { id: "deals" as const, label: "Операции", Icon: ListOrdered },
    { id: "log" as const, label: "Журнал", Icon: FileText },
  ];

  return (
    <div className="relative min-h-screen">
      <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
        <LightRays
          count={3}
          color="rgba(148, 163, 184, 0.14)"
          blur={24}
          speed={28}
          length="50vh"
          className="opacity-80"
        />
      </div>

      <div className="relative z-10 mx-auto max-w-6xl px-4 pb-28 pt-5">
        <TopBar />

        {view === "run" && <RunView />}
        {view === "deals" && <DealsView />}
        {view === "log" && <LogView />}
      </div>

      <RecoveryDialog />
      <ConfirmDialog />

      <nav className="fixed inset-x-0 bottom-5 z-40 flex justify-center px-4">
        <div className="flex items-center gap-1 rounded-2xl border border-border/80 bg-white/90 p-1.5 shadow-lg backdrop-blur-md">
          {nav.map(({ id, label, Icon }) => (
            <button
              key={id}
              type="button"
              title={label}
              onClick={() => setView(id)}
              className={cn(
                "flex size-10 cursor-pointer items-center justify-center rounded-xl transition-colors",
                view === id
                  ? "bg-slate-900 text-white"
                  : "text-slate-500 hover:bg-slate-100 hover:text-slate-900",
              )}
            >
              <Icon className="size-5" />
            </button>
          ))}

          <div className="mx-1 h-7 w-px bg-border" />

          <button
            type="button"
            title={updateBusy ? "Обновляю…" : "Обновить код"}
            disabled={updateBusy}
            onClick={() => void update()}
            className={cn(
              "flex size-10 cursor-pointer items-center justify-center rounded-xl transition-colors",
              updateBusy
                ? "bg-slate-900 text-white"
                : "text-slate-500 hover:bg-slate-100 hover:text-slate-900",
            )}
          >
            {updateBusy ? (
              <Loader2 className="size-5 animate-spin" />
            ) : (
              <Download className="size-5" />
            )}
          </button>
          <button
            type="button"
            title="Перезапустить"
            disabled={updateBusy}
            onClick={() => void restart()}
            className="flex size-10 cursor-pointer items-center justify-center rounded-xl text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 disabled:opacity-40"
          >
            <RotateCcw className="size-5" />
          </button>
          <button
            type="button"
            title="Выключить"
            onClick={() => void shutdown()}
            className="flex size-10 cursor-pointer items-center justify-center rounded-xl text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900"
          >
            <Power className="size-5" />
          </button>

          <div className="mx-1 h-7 w-px bg-border" />

          <button
            type="button"
            title="Стоп"
            disabled={!running}
            onClick={() => void stop()}
            className={cn(
              "flex size-10 cursor-pointer items-center justify-center rounded-xl transition-colors",
              running
                ? "bg-red-50 text-red-600 hover:bg-red-100"
                : "cursor-not-allowed text-slate-300",
            )}
          >
            <Square className="size-4" />
          </button>
        </div>
      </nav>
    </div>
  );
}
