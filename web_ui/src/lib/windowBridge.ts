import { useConsole } from "@/store/console";
import { clearTitleAttention, grabWindowAttention } from "@/lib/attention";

/** Wire backend WebSocket eval API → Zustand (same window.* contract). */
export function installWindowBridge() {
  const sync = () => useConsole.getState();

  window.applyState = (state) => sync().applyState(state);
  window.setStatus = (text, state) => sync().setStatus(text, state);
  window.setRunning = (running, jobMode) => sync().setRunning(!!running, jobMode || "");
  window.appendLog = (text) => sync().appendLog(text);
  window.ingestLogEvents = (events) => sync().ingestLogEvents(events);
  window.updatePipelineProgress = (payload) => sync().updatePipelineProgress(payload);
  window.clearPipelineProgress = () => sync().clearPipelineProgress();
  window.updateReceiptProgress = (payload) => sync().updateReceiptProgress(payload);
  window.clearReceiptProgress = () => sync().clearReceiptProgress();
  window.updateDeclineResult = (payload) => sync().updateDeclineResult(payload);
  window.clearDeclineResult = () => sync().clearDeclineResult();
  window.appendCancelAlert = (payload) => sync().appendCancelAlert(payload);
  window.clearCancelAlerts = () => sync().clearCancelAlerts();
  window.setConfirmPrompt = (prompt, mode) => sync().setConfirmPrompt(prompt, mode);
  window.setRecoveryPrompt = (message, detail, hint, summary, allowRetry) => {
    sync().setRecoveryPrompt(message, detail, hint, summary || {}, !!allowRetry);
  };
  window.hideRecoveryPrompt = () => {
    sync().hideRecoveryPrompt();
  };
  window.showConfirm = async (message, opts = {}) =>
    sync().openDialog({
      title: opts.title || "Подтверждение",
      body: message,
      danger: opts.danger,
    });
  window.grabWindowAttention = grabWindowAttention;
  window.clearTitleAttention = clearTitleAttention;
}
