import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

export function LogView() {
  const logs = useConsole((s) => s.logs);
  const clearLogs = useConsole((s) => s.clearLogs);
  const [q, setQ] = useState("");

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return logs;
    return logs.filter((l) =>
      [l.message, l.service, l.level, l.status].join(" ").toLowerCase().includes(needle),
    );
  }, [logs, q]);

  const copy = async () => {
    const text = logs
      .map((l) => `[${l.time || ""}] ${l.level} ${l.service} ${l.message}`)
      .join("\n");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* ignore */
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
            Live feed
          </p>
          <CardTitle>Журнал</CardTitle>
          <CardDescription>
            <span id="logs-count">{logs.length}</span> событий
          </CardDescription>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={() => clearLogs()}>
            Очистить
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void copy()}>
            Копировать
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Поиск по сообщению или сервису…"
        />
        <div className="max-h-[560px] overflow-auto rounded-xl border border-border bg-white font-mono text-xs">
          {filtered.length === 0 ? (
            <div className="p-10 text-center text-muted-foreground">Пока пусто</div>
          ) : (
            filtered.map((l) => (
              <div
                key={l.id}
                className="grid grid-cols-[54px_70px_1fr] gap-2 border-b border-border/60 px-3 py-2 hover:bg-muted/40 sm:grid-cols-[54px_80px_90px_1fr]"
              >
                <span className="text-muted-foreground">{l.time || "—"}</span>
                <span
                  className={cn(
                    "font-bold uppercase",
                    l.level === "error" && "text-red-600",
                    l.level === "warning" && "text-amber-600",
                    l.level === "info" && "text-teal-700",
                  )}
                >
                  {l.level || "info"}
                </span>
                <span className="hidden truncate text-teal-800 sm:block">{l.service}</span>
                <div className="min-w-0">
                  <div className="truncate text-foreground">{l.message}</div>
                  {l.tags && l.tags.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {l.tags.map((t) => (
                        <Badge key={t} variant="outline">
                          {t}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}
