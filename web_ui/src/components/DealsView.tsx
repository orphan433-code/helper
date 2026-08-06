import { ProgressPanelView } from "@/components/ProgressPanelView";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, apiCall } from "@/lib/api";
import { TRADERS } from "@/lib/types";
import { useConsole } from "@/store/console";

export function DealsView() {
  const s = useConsole((st) => st.settings);
  const patch = useConsole((st) => st.patchSettings);
  const decline = useConsole((st) => st.decline);
  const appendLog = useConsole((st) => st.appendLog);
  const openDialog = useConsole((st) => st.openDialog);
  const clearDeclineResult = useConsole((st) => st.clearDeclineResult);

  const err = (e: string) => {
    appendLog(`[ОШИБКА] ${e}`);
    void openDialog({ title: "Ошибка", body: e, danger: true });
  };

  const selectedTraders = TRADERS.filter((t) => s.redirAccounts[t.id])
    .map((t) => t.traderId)
    .join(",");

  const saveFilters = () =>
    apiCall(() => api().save_redirect_filters(s.redirSkipBog, s.redirVisaOnly), err);

  const redirect = (status: string) =>
    apiCall(async () => {
      await saveFilters();
      return api().start_redirect(
        selectedTraders,
        s.redirMax,
        s.redirMin || null,
        s.redirMaxAmt || null,
        status,
        s.redirSkipBog,
        s.redirVisaOnly,
      );
    }, err);

  const declineRun = async () => {
    const ok = await openDialog({
      title: "Снятие с витрины",
      body: "Отменяет ожидающие сделки выбранного банка. Отката не будет.",
      danger: true,
    });
    if (!ok) return;
    clearDeclineResult();
    await apiCall(() => api().start_decline(s.declineBank), err);
  };

  return (
    <Card>
      <CardHeader>
        <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
          Ops
        </p>
        <CardTitle>Операции</CardTitle>
        <CardDescription>Передать сделки на аккаунт или снять с витрины</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="redirect">
          <TabsList>
            <TabsTrigger value="redirect">Передать</TabsTrigger>
            <TabsTrigger value="decline">Снять</TabsTrigger>
          </TabsList>

          <TabsContent value="redirect" className="space-y-4">
            <div className="space-y-2">
              <Label>Куда передать</Label>
              <div className="grid grid-cols-3 gap-2">
                {TRADERS.map((t) => (
                  <label
                    key={t.id}
                    className="flex cursor-pointer items-center justify-between gap-2 rounded-xl border border-border bg-muted/30 px-3 py-2.5"
                  >
                    <span className="text-sm font-semibold">{t.label}</span>
                    <Switch
                      checked={!!s.redirAccounts[t.id]}
                      onCheckedChange={(v) =>
                        patch({
                          redirAccounts: { ...s.redirAccounts, [t.id]: v },
                        })
                      }
                    />
                  </label>
                ))}
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label>Сколько</Label>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={s.redirMax}
                  onChange={(e) => patch({ redirMax: Number(e.target.value) || 1 })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>От, USDT</Label>
                <Input
                  value={s.redirMin}
                  placeholder="любая"
                  onChange={(e) => patch({ redirMin: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>До, USDT</Label>
                <Input
                  value={s.redirMaxAmt}
                  placeholder="любая"
                  onChange={(e) => patch({ redirMaxAmt: e.target.value })}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label>Фильтры</Label>
              <label className="flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-border bg-muted/30 px-3 py-3">
                <span>
                  <span className="block text-sm font-semibold">Пропуск Bank of Georgia</span>
                  <span className="text-xs text-muted-foreground">Пропуск BoG</span>
                </span>
                <Switch
                  checked={s.redirSkipBog}
                  onCheckedChange={(v) => patch({ redirSkipBog: v })}
                />
              </label>
              <label className="flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-border bg-muted/30 px-3 py-3">
                <span>
                  <span className="block text-sm font-semibold">Только Visa</span>
                  <span className="text-xs text-muted-foreground">Редирект только Visa</span>
                </span>
                <Switch
                  checked={s.redirVisaOnly}
                  onCheckedChange={(v) => patch({ redirVisaOnly: v })}
                />
              </label>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button className="flex-1" onClick={() => void redirect("new")}>
                Редирект из (NEW)
              </Button>
              <Button
                className="flex-1"
                variant="secondary"
                onClick={() => void redirect("pending")}
              >
                Редирект из (PENDING)
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="decline" className="space-y-4">
            <div className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3">
              <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-amber-200 font-bold text-amber-900">
                !
              </div>
              <div>
                <div className="text-sm font-bold">Снятие с витрины</div>
                <p className="text-sm text-muted-foreground">
                  Отменяет ожидающие сделки выбранного банка. Отката не будет.
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <Label>Банк</Label>
              <div className="grid grid-cols-2 gap-2">
                {(["tbc", "bog"] as const).map((b) => (
                  <button
                    key={b}
                    type="button"
                    onClick={() => patch({ declineBank: b })}
                    className={
                      s.declineBank === b
                        ? "rounded-xl border border-primary bg-primary/10 px-3 py-2.5 text-sm font-semibold text-primary cursor-pointer"
                        : "rounded-xl border border-border bg-muted/30 px-3 py-2.5 text-sm font-semibold cursor-pointer"
                    }
                  >
                    {b === "tbc" ? "TBC" : "BoG"}
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                TBC — по названию банка. BoG — карты 548888 и Bank of Georgia.
              </p>
            </div>

            <Button variant="danger" onClick={() => void declineRun()}>
              Снять сделки
            </Button>
          </TabsContent>
        </Tabs>

        <ProgressPanelView panel={decline} />
      </CardContent>
    </Card>
  );
}
