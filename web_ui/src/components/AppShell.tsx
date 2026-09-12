import { useState, type ReactNode } from "react";
import {
  CloudDownload,
  Loader2,
  Octagon,
  RefreshCw,
  Power,
  ScrollText,
  Settings,
  Sparkles,
  Play,
  ArrowLeftRight,
  Users,
} from "lucide-react";
import { TopBar } from "@/components/TopBar";
import { RunView } from "@/components/RunView";
import { DealsView } from "@/components/DealsView";
import { AgentView } from "@/components/AgentView";
import { LogView } from "@/components/LogView";
import { RecoveryDialog } from "@/components/RecoveryDialog";
import { RatesConfirmDialog, DryStopDialog } from "@/components/RatesConfirmDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { BusyOverlay } from "@/components/BusyOverlay";
import { ResultOverlay } from "@/components/ResultOverlay";
import { SettingsBundleDialog } from "@/components/SettingsBundlePanel";
import { api, apiCall, serverPost } from "@/lib/api";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

type ViewId = "run" | "deals" | "agent" | "log";

function NavDivider() {
  return <div className="mx-0.5 h-7 w-px shrink-0 bg-border" />;
}

function NavTab({
  active,
  label,
  icon: Icon,
  onClick,
}: {
  active: boolean;
  label: string;
  icon: typeof Play;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex cursor-pointer items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-primary text-primary-foreground shadow-sm"
          : "text-foreground/55 hover:bg-foreground/[0.06] hover:text-foreground",
      )}
    >
      <Icon className="size-3.5 opacity-80" />
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
  description?: string;
  children: ReactNode;
}) {
  return (
    <div className="group/action relative">
      {children}
      <div
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 w-max max-w-[12rem] -translate-x-1/2 rounded-lg border border-border/40 bg-background/95 px-2.5 py-1.5 text-left opacity-0 shadow-xl backdrop-blur-xl transition-opacity duration-150 group-hover/action:opacity-100"
      >
        <p className="text-xs font-semibold text-foreground">{title}</p>
        {description && (
          <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{description}</p>
        )}
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
  description?: string;
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
          danger && !disabled && "bg-danger-soft text-danger hover:bg-rose-500/10",
          active && !danger && "bg-primary text-primary-foreground",
          !danger && !active && !disabled && "text-foreground/55 hover:bg-foreground/[0.06] hover:text-foreground",
        )}
      >
        {children}
      </button>
    </ActionTip>
  );
}

function GearMenuItem({
  disabled,
  onClick,
  children,
}: {
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm text-foreground/80 transition-colors",
        disabled ? "cursor-not-allowed opacity-40" : "hover:bg-foreground/[0.06]",
      )}
    >
      {children}
    </button>
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

  const tabs: { id: ViewId; label: string; icon: typeof Play }[] = [
    { id: "run", label: "Запуск", icon: Play },
    { id: "deals", label: "Операции", icon: ArrowLeftRight },
    { id: "agent", label: "Команда", icon: Sparkles },
    { id: "log", label: "Журнал", icon: ScrollText },
  ];

  return (
    <div className="relative min-h-screen">
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-0 h-[520px] w-[520px] -translate-x-1/2 rounded-full bg-foreground/[0.035] blur-[140px]" />
        <div className="absolute bottom-0 right-0 h-[360px] w-[360px] rounded-full bg-foreground/[0.025] blur-[120px]" />
        <div className="absolute left-1/4 top-1/2 h-[400px] w-[400px] rounded-full bg-primary/[0.02] blur-[150px]" />
      </div>
      <div className="relative z-10 mx-auto max-w-6xl px-4 pb-28 pt-5">
        <TopBar />

        {view === "run" && <RunView />}
        {view === "deals" && <DealsView />}
        {view === "agent" && <AgentView />}
        {view === "log" && <LogView />}
      </div>

      <BusyOverlay />
      <ResultOverlay />
      <RecoveryDialog />
      <RatesConfirmDialog />
      <DryStopDialog />
      <ConfirmDialog />
      <SettingsBundleDialog open={bundleOpen} onOpenChange={setBundleOpen} />

      <nav className="fixed inset-x-0 bottom-5 z-40 flex justify-center px-4">
        <div className="flex max-w-full flex-wrap items-center justify-center gap-1 rounded-2xl border border-border/40 bg-background/60 p-1.5 shadow-lg backdrop-blur-xl">
          {tabs.map(({ id, label, icon }) => (
            <NavTab
              key={id}
              label={label}
              icon={icon}
              active={view === id}
              onClick={() => setView(id)}
            />
          ))}

          <NavDivider />

          <div className="relative">
            <ActionBtn
              title="Сервис"
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
                <div className="absolute bottom-full left-1/2 z-50 mb-2 w-52 -translate-x-1/2 rounded-xl border border-border/40 bg-background/95 p-1 shadow-xl backdrop-blur-xl">
                  <GearMenuItem
                    onClick={() => {
                      setGearOpen(false);
                      setBundleOpen(true);
                    }}
                  >
                    <Users className="size-4 shrink-0 text-foreground/55" />
                    <span>Настройки</span>
                  </GearMenuItem>
                  <GearMenuItem
                    disabled={updateBusy}
                    onClick={() => {
                      setGearOpen(false);
                      void update();
                    }}
                  >
                    {updateBusy ? (
                      <Loader2 className="size-4 shrink-0 animate-spin text-foreground/55" />
                    ) : (
                      <CloudDownload className="size-4 shrink-0 text-foreground/55" />
                    )}
                    <span>Обновить</span>
                  </GearMenuItem>
                  <GearMenuItem
                    disabled={updateBusy}
                    onClick={() => {
                      setGearOpen(false);
                      void restart();
                    }}
                  >
                    <RefreshCw className="size-4 shrink-0 text-foreground/55" />
                    <span>Перезапуск</span>
                  </GearMenuItem>
                  <GearMenuItem
                    onClick={() => {
                      setGearOpen(false);
                      void shutdown();
                    }}
                  >
                    <Power className="size-4 shrink-0 text-foreground/55" />
                    <span>Выключить</span>
                  </GearMenuItem>
                </div>
              </>
            )}
          </div>

          <NavDivider />

          <ActionTip title="Стоп">
            <button
              type="button"
              disabled={!running}
              onClick={() => void stop()}
              className={cn(
                "flex h-10 cursor-pointer items-center justify-center gap-1.5 rounded-xl px-3 text-sm font-semibold transition-colors",
                running
                  ? "bg-danger text-white hover:brightness-95"
                  : "text-foreground/40",
                !running && "cursor-not-allowed opacity-40",
              )}
            >
              <Octagon className="size-4 fill-current" />
              {running && "Стоп"}
            </button>
          </ActionTip>
        </div>
      </nav>
    </div>
  );
}
