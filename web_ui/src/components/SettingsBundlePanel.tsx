import { useRef, useState, type DragEvent } from "react";
import { Download, FileArchive, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

type ImportReport = {
  ok?: boolean;
  error?: string;
  imported?: { path: string; action: string }[];
  backups?: string[];
  fill_locally?: string[];
  includes_secrets?: boolean;
};

export function SettingsBundleDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const appendLog = useConsole((st) => st.appendLog);
  const applyState = useConsole((st) => st.applyState);
  const openDialog = useConsole((st) => st.openDialog);
  const running = useConsole((st) => st.running);

  const inputRef = useRef<HTMLInputElement>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [includeSecrets, setIncludeSecrets] = useState(true);
  const [dragOver, setDragOver] = useState(false);
  const [lastReport, setLastReport] = useState<ImportReport | null>(null);

  const err = (e: string) => {
    appendLog(`[SETTINGS] ${e}`);
    void openDialog({ title: "Настройки", body: e, danger: true, alert: true });
  };

  const exportBundle = async () => {
    if (exportBusy) return;
    setExportBusy(true);
    try {
      const qs = includeSecrets ? "?include_secrets=true" : "";
      const r = await fetch(`/api/settings/export${qs}`, { credentials: "same-origin" });
      if (!r.ok) throw new Error(await r.text());
      const blob = await r.blob();
      const cd = r.headers.get("content-disposition") || "";
      const match = /filename=\"?([^\";]+)\"?/i.exec(cd);
      const name = match?.[1] || "tjs-settings.tjsbundle.zip";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
      appendLog(
        `[SETTINGS] Экспорт: ${name}${includeSecrets ? " (с PIN и API)" : ""}`,
      );
    } catch (e) {
      err(String(e));
    } finally {
      setExportBusy(false);
    }
  };

  const importBundle = async (file: File) => {
    if (importBusy || running) return;
    const ok = await openDialog({
      title: "Применить настройки",
      body: `Файл «${file.name}» заменит team-настройки. Локальные значения сохранятся, если в bundle секреты не заполнены.`,
      danger: true,
      confirmLabel: "Применить",
    });
    if (!ok) return;

    setImportBusy(true);
    setLastReport(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch("/api/settings/import", {
        method: "POST",
        credentials: "same-origin",
        body: fd,
      });
      const data = (await r.json()) as ImportReport & { state?: Record<string, unknown> };
      if (!r.ok || data.error) {
        throw new Error(data.error || `HTTP ${r.status}`);
      }
      if (data.state) applyState(data.state);
      else applyState(await api().get_state());
      setLastReport(data);
      appendLog(
        `[SETTINGS] Импорт OK: ${(data.imported || []).map((x) => x.path).join(", ")}`,
      );
      const missing = (data.fill_locally || []).filter(Boolean);
      const hadSecrets = Boolean(data.includes_secrets);
      await openDialog({
        title: "Настройки применены",
        body: [
          (data.imported || []).map((x) => `✓ ${x.path}`).join("\n"),
          "",
          hadSecrets
            ? "PIN и API-ключи применены из bundle."
            : "Проверь локально: PIN, Gemini-ключ, логин PlatCore.",
          missing.length
            ? `\nЕщё заполнить:\n${missing.map((x) => `- ${x}`).join("\n")}`
            : "",
        ]
          .filter(Boolean)
          .join("\n"),
        alert: true,
      });
    } catch (e) {
      err(String(e));
    } finally {
      setImportBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const pickFile = () => {
    if (!importBusy && !running) inputRef.current?.click();
  };

  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    if (!importBusy && !running) setDragOver(true);
  };

  const onDragLeave = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void importBundle(file);
  };

  const busy = exportBusy || importBusy;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Настройки команды</DialogTitle>
          <p className="text-xs leading-relaxed text-muted-foreground">
            Один zip на всех — config, decline, фильтры UI. Логин PlatCore у каждого
            отдельно (browser_profile).
          </p>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-xs">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={includeSecrets}
              disabled={busy}
              onChange={(e) => setIncludeSecrets(e.target.checked)}
            />
            <span>
              <span className="font-medium text-foreground">Включить PIN и API</span>
              <span className="mt-0.5 block text-muted-foreground">
                Для личной передачи коллегам — Gemini-ключ, bank.pin, token decline.
              </span>
            </span>
          </label>

          <input
            ref={inputRef}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void importBundle(f);
            }}
          />

          <div className="relative">
            <button
              type="button"
              title="Скачать zip для команды"
              disabled={busy}
              onClick={(e) => {
                e.stopPropagation();
                void exportBundle();
              }}
              className={cn(
                "absolute right-2 top-2 z-10 flex size-8 cursor-pointer items-center justify-center rounded-lg border border-border/80 bg-white text-slate-600 transition-colors",
                busy ? "cursor-not-allowed opacity-40" : "hover:bg-slate-50 hover:text-slate-900",
              )}
            >
              {exportBusy ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Download className="size-4" />
              )}
            </button>

            <button
              type="button"
              disabled={busy || running}
              onClick={pickFile}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              onDrop={onDrop}
              className={cn(
                "flex w-full cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-10 text-center transition-colors",
                dragOver
                  ? "border-primary/50 bg-primary/5"
                  : "border-border/80 bg-white hover:border-slate-300 hover:bg-slate-50/80",
                (busy || running) && "cursor-not-allowed opacity-50",
              )}
            >
              {importBusy ? (
                <Loader2 className="size-8 animate-spin text-muted-foreground" />
              ) : (
                <FileArchive className="size-8 text-muted-foreground/70" />
              )}
              <div>
                <p className="text-sm font-medium text-foreground">
                  {dragOver ? "Отпустите файл" : "Загрузить .zip"}
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  перетащите или нажмите
                </p>
              </div>
            </button>
          </div>

          {lastReport?.imported?.length ? (
            <ul className="rounded-xl border border-border/60 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
              {lastReport.imported.map((x) => (
                <li key={x.path}>✓ {x.path}</li>
              ))}
              {(lastReport.backups || []).map((b) => (
                <li key={b} className="text-slate-400">
                  backup: {b}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
