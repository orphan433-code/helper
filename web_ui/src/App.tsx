import { useEffect } from "react";
import { installWindowBridge } from "@/lib/windowBridge";
import { api } from "@/lib/api";
import { useConsole } from "@/store/console";
import { AppShell } from "@/components/AppShell";

export default function App() {
  const applyState = useConsole((s) => s.applyState);
  const setStatus = useConsole((s) => s.setStatus);
  const appendLog = useConsole((s) => s.appendLog);
  const ingestLogEvents = useConsole((s) => s.ingestLogEvents);
  const setRunning = useConsole((s) => s.setRunning);
  const patchAdb = useConsole((s) => s.applyState);

  useEffect(() => {
    installWindowBridge();

    const boot = async () => {
      try {
        const state = await api().get_state();
        applyState(state);
      } catch (err) {
        appendLog(`[boot] ${err}`);
      }
      try {
        const r = await api().check_adb();
        patchAdb({
          adb_device: r.adb_device || "не подключён",
          adb_ok: !!r.adb_ok,
        });
      } catch {
        /* ignore */
      }
    };

    const onReady = () => {
      void boot();
    };
    window.addEventListener("pywebviewready", onReady);
    if (window.pywebview?.api) void boot();

    let pollBusy = false;
    const poll = window.setInterval(() => {
      if (pollBusy || document.hidden) return;
      pollBusy = true;
      void (async () => {
        try {
          const events = await api().poll_logs();
          if (Array.isArray(events)) ingestLogEvents(events);
          else if (typeof events === "string" && events) appendLog(events);
        } catch {
          /* ignore */
        } finally {
          pollBusy = false;
        }
      })();
    }, 1000);

    const idleWatch = window.setInterval(() => {
      const st = useConsole.getState();
      if (
        !st.running &&
        (st.statusKind === "running" ||
          /Продолжаю обработку|Обрабатываю сделки|Повторяю|Пропускаю|Останавливаю|Загружаю чеки/i.test(
            st.statusText,
          )) &&
        !st.recovery.open
      ) {
        setStatus("Можно запускать", "idle");
        setRunning(false, "");
      }
    }, 2000);

    return () => {
      window.removeEventListener("pywebviewready", onReady);
      window.clearInterval(poll);
      window.clearInterval(idleWatch);
    };
  }, [applyState, appendLog, ingestLogEvents, patchAdb, setRunning, setStatus]);

  return <AppShell />;
}
