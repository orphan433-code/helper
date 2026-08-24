import { useState, type ReactNode } from "react";
import {
  CloudDownload,
  Loader2,
  Octagon,
  RefreshCw,
  Power,
  Settings,
  Users,
} from "lucide-react";
import { TopBar } from "@/components/TopBar";
import { RunView } from "@/components/RunView";
import { DealsView } from "@/components/DealsView";
import { LogView } from "@/components/LogView";
import { RecoveryDialog } from "@/components/RecoveryDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { BusyOverlay } from "@/components/BusyOverlay";
import { ResultOverlay } from "@/components/ResultOverlay";
import { SettingsBundleDialog } from "@/components/SettingsBundlePanel";
import { LightRays } from "@/components/ui/light-rays";
import { api, apiCall, serverPost } from "@/lib/api";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

type ViewId = "run" | "deals" | "log";

function NavDivider() {
  return <div className="mx-0.5 h-7 w-px shrink-0 bg-border" />;
}

function NavTab({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "cursor-pointer rounded-xl px-3.5 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-slate-900 text-white shadow-sm"
          : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
      )}
    >
      {label}
    </button>
  );
}

function ActionTip({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="group/action relative">
      {children}
      <div
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 w-max max-w-[13rem] -translate-x-1/2 rounded-lg border border-border/80 bg-white px-2.5 py-2 text-left opacity-0 shadow-lg transition-opacity duration-150 group-hover/action:opacity-100"
      >
        <p className="text-xs font-semibold text-foreground">{title}</p>
        <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

function ActionBtn({
  title,
  description,
  disabled,
  danger,
  active,
  onClick,
  children,
}: {
  title: string;
  description: string;
  disabled?: boolean;
  danger?: boolean;
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <ActionTip title={title} description={description}>
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        className={cn(
          "flex size-10 cursor-pointer items-center justify-center rounded-xl transition-colors",
          disabled && "cursor-not-allowed opacity-40",
          danger && !disabled && "bg-red-50 text-red-600 hover:bg-red-100",
          active && !danger && "bg-slate-900 text-white",
          !danger && !active && !disabled && "text-slate-500 hover:bg-slate-100 hover:text-slate-900",
        )}
      >
        {children}
      </button>
    </ActionTip>
  );
}

function GearMenuItem({
  title,
  description,
  disabled,
  onClick,
  children,
}: {
  title: string;
  description: string;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <ActionTip title={title} description={description}>
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        className={cn(
          "flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm text-slate-700 transition-colors",
          disabled ? "cursor-not-allowed opacity-40" : "hover:bg-slate-100",
        )}
      >
        {children}
      </button>
    </ActionTip>
  );
}

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
  const [gearOpen, setGearOpen] = useState(false);
  const [bundleOpen, setBundleOpen] = useState(false);

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
      title: "Выключить TJS",
      body: "Сервер остановится",
      danger: true,
      confirmLabel: "Выключить",
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
        title: "Сначала стоп",
        body: "Останови задачу, потом обновляй",
        alert: true,
      });
      return;
    }
    const ok = await openDialog({
      title: "Обновить код",
      body: "С GitHub. Конфиг не затирается",
      confirmLabel: "Обновить",
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
          title: "Не обновилось",
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
        title: "Готово",
        body: msg,
        alert: true,
      });
    } catch (e) {
      const raw = String(e);
      const msg =
        /failed to fetch/i.test(raw) || /networkerror/i.test(raw)
          ? [
              "Связь с сервером оборвалась (Failed to fetch).",
              "Часто: долгий pip/playwright или процесс упал.",
              "Проверь терминал runtjsnew — если мёртв, запусти снова.",
              "Потом: bash ensure_venv.sh и кнопка ↻.",
            ].join("\n")
          : raw;
      appendLog(`[UPDATE] ${msg}\n`);
      setStatus("Ошибка обновления", "error");
      await openDialog({
        title: "Не обновилось",
        body: msg,
        danger: true,
        alert: true,
      });
    } finally {
      setUpdateBusy(false);
    }
  };

  const tabs: { id: ViewId; label: string }[] = [
    { id: "run", label: "Запуск" },
    { id: "deals", label: "AI команда" },
    { id: "log", label: "Журнал" },
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

      <BusyOverlay />
      <ResultOverlay />
      <RecoveryDialog />
      <ConfirmDialog />
      <SettingsBundleDialog open={bundleOpen} onOpenChange={setBundleOpen} />

      <nav className="fixed inset-x-0 bottom-5 z-40 flex justify-center px-4">
        <div className="flex max-w-full flex-wrap items-center justify-center gap-1 rounded-2xl border border-border/80 bg-white/90 p-1.5 shadow-lg backdrop-blur-md">
          {tabs.map(({ id, label }) => (
            <NavTab
              key={id}
              label={label}
              active={view === id}
              onClick={() => setView(id)}
            />
          ))}

          <NavDivider />

          <div className="relative">
            <ActionBtn
              title="Сервис"
              description="Настройки команды, обновление, перезапуск и выключение."
              active={gearOpen}
              onClick={() => setGearOpen((v) => !v)}
            >
              <Settings className="size-5" />
            </ActionBtn>

            {gearOpen && (
              <>
                <button
                  type="button"
                  aria-label="Закрыть меню"
                  className="fixed inset-0 z-40 cursor-default"
                  onClick={() => setGearOpen(false)}
                />
                <div className="absolute bottom-full left-1/2 z-50 mb-2 w-52 -translate-x-1/2 rounded-xl border border-border/80 bg-white p-1 shadow-lg">
                  <GearMenuItem
                    title="Настройки команды"
                    description="Скачать или загрузить zip с team-настройками."
                    onClick={() => {
                      setGearOpen(false);
                      setBundleOpen(true);
                    }}
                  >
                    <Users className="size-4 shrink-0 text-slate-500" />
                    <span>Настройки команды</span>
                  </GearMenuItem>
                  <GearMenuItem
                    title="Обновить код"
                    description="Скачивает последнюю версию с GitHub. Конфиг не затирается."
                    disabled={updateBusy}
                    onClick={() => {
                      setGearOpen(false);
                      void update();
                    }}
                  >
                    {updateBusy ? (
                      <Loader2 className="size-4 shrink-0 animate-spin text-slate-500" />
                    ) : (
                      <CloudDownload className="size-4 shrink-0 text-slate-500" />
                    )}
                    <span>Обновить код</span>
                  </GearMenuItem>
                  <GearMenuItem
                    title="Перезапустить"
                    description="Перезапускает движок TJS без выключения сервера."
                    disabled={updateBusy}
                    onClick={() => {
                      setGearOpen(false);
                      void restart();
                    }}
                  >
                    <RefreshCw className="size-4 shrink-0 text-slate-500" />
                    <span>Перезапустить</span>
                  </GearMenuItem>
                  <GearMenuItem
                    title="Выключить"
                    description="Полностью останавливает сервер TJS."
                    onClick={() => {
                      setGearOpen(false);
                      void shutdown();
                    }}
                  >
                    <Power className="size-4 shrink-0 text-slate-500" />
                    <span>Выключить</span>
                  </GearMenuItem>
                </div>
              </>
            )}
          </div>

          <NavDivider />

          <ActionBtn
            title="Стоп"
            description="Останавливает текущую задачу — редирект, отмену или переводы."
            disabled={!running}
            danger={running}
            onClick={() => void stop()}
          >
            <Octagon className="size-4 fill-current" />
          </ActionBtn>
        </div>
      </nav>
    </div>
  );
}
