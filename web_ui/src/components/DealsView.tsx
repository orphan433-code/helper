import { type ReactNode } from "react";
import { BlurFade } from "@/components/ui/blur-fade";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { BentoCard, BentoGrid } from "@/components/ui/bento-grid";
import { RippleButton } from "@/components/ui/ripple-button";
import { api, apiCall } from "@/lib/api";
import { TRADERS } from "@/lib/types";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

export function DealsView() {
  const s = useConsole((st) => st.settings);
  const patch = useConsole((st) => st.patchSettings);
  const running = useConsole((st) => st.running);
  const jobMode = useConsole((st) => st.jobMode);
  const appendLog = useConsole((st) => st.appendLog);
  const openDialog = useConsole((st) => st.openDialog);
  const clearDeclineResult = useConsole((st) => st.clearDeclineResult);

  const err = (e: string) => {
    appendLog(`[ОШИБКА] ${e}`);
    void openDialog({ title: "Ошибка", body: e, danger: true, alert: true });
  };

  const opsBusy = running && (jobMode === "redirect" || jobMode === "decline");
  const selectedLabels = TRADERS.filter((t) => s.redirAccounts[t.id]).map((t) => t.label);
  const selectedTraders = TRADERS.filter((t) => s.redirAccounts[t.id]).map((t) => t.traderId);

  const saveFilters = () =>
    apiCall(() => api().save_redirect_filters(s.redirSkipBog, s.redirVisaOnly), err);

  const redirect = async (status: string) => {
    if (opsBusy) return;
    if (!selectedTraders.length) {
      await openDialog({
        title: "Редирект",
        body: "Выбери хотя бы один аккаунт",
        alert: true,
      });
      return;
    }
    const maxN = parseInt(String(s.redirMax).trim(), 10);
    if (!Number.isFinite(maxN) || maxN < 1) {
      await openDialog({
        title: "Редирект",
        body: "Укажи количество",
        alert: true,
      });
      return;
    }

    const where = selectedLabels.join(", ");
    const ok = await openDialog({
      title: "Передать сделки",
      body: `${maxN} шт. · ${status === "pending" ? "PENDING" : "NEW"} → ${where}`,
      danger: true,
      confirmLabel: "Передать",
    });
    if (!ok) return;

    clearDeclineResult();
    await apiCall(async () => {
      await saveFilters();
      return api().start_redirect(
        selectedTraders,
        maxN,
        s.redirMin || null,
        s.redirMaxAmt || null,
        status,
        s.redirSkipBog,
        s.redirVisaOnly,
      );
    }, err);
  };

  const declineRun = async () => {
    if (opsBusy) return;
    const label = s.declineBank === "tbc" ? "TBC" : "BoG";
    const hint =
      s.declineBank === "tbc"
        ? "имя TBC или карты 4315…"
        : "имя Bank of Georgia или карты 548888…";
    const ok = await openDialog({
      title: "Отменить сделки",
      body: `Банк ${label} (${hint})`,
      danger: true,
      confirmLabel: "Отменить",
    });
    if (!ok) return;
    clearDeclineResult();
    await apiCall(() => api().start_decline(s.declineBank), err);
  };

  return (
    <BlurFade delay={0.05} inView>
    <BentoGrid className="lg:grid-rows-[auto]">
      <BentoCard className="col-span-3 lg:col-span-2" name="Редирект">
        <div className="flex flex-col gap-3">
          <div className="space-y-1.5">
            <Label>Куда</Label>
            <div className="grid grid-cols-3 gap-2">
              {TRADERS.map((t) => (
                <label
                  key={t.id}
                  className="flex cursor-pointer items-center justify-between gap-2 rounded-xl border border-border/80 bg-muted/25 px-3 py-2.5"
                >
                  <span className="text-sm font-semibold">{t.label}</span>
                  <Switch
                    checked={!!s.redirAccounts[t.id]}
                    disabled={opsBusy}
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
            <Field label="Сколько">
              <Input
                inputMode="numeric"
                min={1}
                max={100}
                value={s.redirMax}
                placeholder="1–100"
                disabled={opsBusy}
                onChange={(e) =>
                  patch({
                    redirMax: e.target.value.replace(/[^\d]/g, "").slice(0, 3),
                  })
                }
              />
            </Field>
            <Field label="От">
              <Input
                value={s.redirMin}
                placeholder="USDT"
                disabled={opsBusy}
                onChange={(e) => patch({ redirMin: e.target.value })}
              />
            </Field>
            <Field label="До">
              <Input
                value={s.redirMaxAmt}
                placeholder="USDT"
                disabled={opsBusy}
                onChange={(e) => patch({ redirMaxAmt: e.target.value })}
              />
            </Field>
          </div>

          <div className="grid gap-2">
            <ToggleRow
              label="Пропуск BoG"
              checked={s.redirSkipBog}
              disabled={opsBusy}
              onChange={(v) => patch({ redirSkipBog: v })}
            />
            <ToggleRow
              label="Только Visa"
              checked={s.redirVisaOnly}
              disabled={opsBusy}
              onChange={(v) => patch({ redirVisaOnly: v })}
            />
          </div>

          <div className="flex flex-wrap gap-2 pt-1">
            <RippleButton
              disabled={opsBusy}
              onClick={() => void redirect("new")}
              className="flex-1 border-primary bg-primary text-primary-foreground hover:brightness-105"
            >
              NEW
            </RippleButton>
            <RippleButton
              disabled={opsBusy}
              onClick={() => void redirect("pending")}
              rippleColor="#cbd5e1"
              className="flex-1 border-border bg-secondary text-secondary-foreground hover:bg-slate-200/80"
            >
              PENDING
            </RippleButton>
          </div>
        </div>
      </BentoCard>

      <BentoCard
        className="col-span-3 lg:col-span-1 lg:sticky lg:top-4 lg:self-start"
        name="Отмена"
      >
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2">
            {(["tbc", "bog"] as const).map((b) => (
              <button
                key={b}
                type="button"
                disabled={opsBusy}
                onClick={() => patch({ declineBank: b })}
                className={cn(
                  "cursor-pointer rounded-xl border px-3 py-2.5 text-sm font-semibold transition-colors disabled:opacity-60",
                  s.declineBank === b
                    ? "border-slate-400 bg-slate-50"
                    : "border-border/80 bg-muted/25 hover:bg-muted/40",
                )}
              >
                {b === "tbc" ? "TBC" : "BoG"}
              </button>
            ))}
          </div>
          <RippleButton
            disabled={opsBusy}
            onClick={() => void declineRun()}
            className="w-full border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
            rippleColor="#fecaca"
          >
            Отменить
          </RippleButton>
        </div>
      </BentoCard>
    </BentoGrid>
    </BlurFade>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function ToggleRow({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-2 rounded-xl border border-border/80 bg-muted/25 px-3 py-2.5">
      <span className="text-sm font-semibold text-foreground">{label}</span>
      <Switch checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </label>
  );
}
