import type { ReactNode } from "react";
import { ProgressPanelView } from "@/components/ProgressPanelView";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { BentoCard, BentoGrid } from "@/components/ui/bento-grid";
import { RippleButton } from "@/components/ui/ripple-button";
import { api, apiCall } from "@/lib/api";
import { useConsole } from "@/store/console";
import { cn } from "@/lib/utils";

export function RunView() {
  const s = useConsole((st) => st.settings);
  const patch = useConsole((st) => st.patchSettings);
  const running = useConsole((st) => st.running);
  const jobMode = useConsole((st) => st.jobMode);
  const waiting = useConsole((st) => st.waitingConfirm);
  const confirmMode = useConsole((st) => st.confirmMode);
  const adbOk = useConsole((st) => st.adbOk);
  const adbText = useConsole((st) => st.adbText);
  const mediaDir = useConsole((st) => st.mediaDir);
  const pipeline = useConsole((st) => st.pipeline);
  const receipts = useConsole((st) => st.receipts);
  const cancels = useConsole((st) => st.cancels);
  const appendLog = useConsole((st) => st.appendLog);
  const openDialog = useConsole((st) => st.openDialog);
  const clearCancelAlerts = useConsole((st) => st.clearCancelAlerts);
  const applyState = useConsole((st) => st.applyState);

  const err = (e: string) => {
    appendLog(`[ОШИБКА] ${e}`);
    void openDialog({ title: "Ошибка", body: e, danger: true });
  };

  const checkAdb = () =>
    apiCall(async () => {
      const r = await api().check_adb();
      applyState({
        adb_device: r.adb_device || "не подключён",
        adb_ok: !!r.adb_ok,
      });
      return r;
    }, err);

  const save = () =>
    apiCall(
      () =>
        api().save_settings(
          s.maxDeals,
          s.minAmount.trim(),
          s.maxAmount.trim(),
          s.allowVisa,
          s.allowMastercard,
          s.emptyPasses,
          s.fromPending,
        ),
      err,
    );

  const login = () => apiCall(() => api().start_login(), err);
  const start = () =>
    apiCall(
      () =>
        api().start_pipeline(
          s.maxDeals,
          s.minAmount.trim(),
          s.maxAmount.trim(),
          s.allowVisa,
          s.allowMastercard,
          s.emptyPasses,
          s.fromPending,
        ),
      err,
    );
  const confirmLogin = () => apiCall(() => api().confirm("login"), err);
  const confirmReceipts = () => apiCall(() => api().confirm("receipts"), err);
  const openFolder = () => apiCall(() => api().open_videos_folder(), err);

  const loginWaiting = waiting && confirmMode === "login";
  const receiptsWaiting = waiting && confirmMode === "pipeline";
  const startActive = running && jobMode === "pipeline" && !receiptsWaiting;

  return (
    <div className="space-y-3">
      <BentoGrid className="lg:grid-rows-[auto_auto_auto_auto]">
        <BentoCard
          className="col-span-3 lg:col-span-2 lg:row-start-1"
          name="Телефон"
          description="Проверьте USB-отладку перед запуском."
          tone={adbOk ? "ok" : "warn"}
          badge={<StepBadge n={1} tone={adbOk ? "ok" : "warn"} />}
          cta={
            <RippleButton
              onClick={() => void checkAdb()}
              rippleColor="#cbd5e1"
              className="border-border bg-secondary text-secondary-foreground hover:bg-slate-200/80"
            >
              Проверить
            </RippleButton>
          }
        >
          <div
            className={cn(
              "rounded-xl border px-3 py-2.5",
              adbOk ? "border-emerald-200 bg-emerald-50/80" : "border-amber-200 bg-amber-50/90",
            )}
          >
            <div className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
              Устройство
            </div>
            <div className="mt-0.5 font-mono text-sm font-medium">{adbText}</div>
          </div>
        </BentoCard>

        <BentoCard
          className="col-span-3 lg:col-span-1 lg:row-span-4 lg:row-start-1 lg:col-start-3"
          name="Фильтры"
          description="Параметры запуска пайплайна"
        >
          <div className="flex h-full flex-col gap-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Макс. сделок">
                <Input
                  type="number"
                  min={1}
                  max={50}
                  value={s.maxDeals}
                  onChange={(e) => patch({ maxDeals: Number(e.target.value) || 1 })}
                />
              </Field>
              <Field label="Пустых проходов">
                <Input
                  type="number"
                  min={1}
                  max={20}
                  value={s.emptyPasses}
                  onChange={(e) => patch({ emptyPasses: Number(e.target.value) || 1 })}
                />
              </Field>
            </div>
            <Field label="Сумма, USDT">
              <div className="flex items-center gap-2">
                <Input
                  placeholder="от"
                  value={s.minAmount}
                  onChange={(e) => patch({ minAmount: e.target.value })}
                />
                <span className="text-muted-foreground">–</span>
                <Input
                  placeholder="до"
                  value={s.maxAmount}
                  onChange={(e) => patch({ maxAmount: e.target.value })}
                />
              </div>
            </Field>
            <Field label="Карты">
              <div className="grid gap-2">
                <ToggleRow
                  label="Visa"
                  checked={s.allowVisa}
                  onChange={(v) => patch({ allowVisa: v })}
                />
                <ToggleRow
                  label="Mastercard"
                  checked={s.allowMastercard}
                  onChange={(v) => patch({ allowMastercard: v })}
                />
              </div>
            </Field>
            <Field label="Режим">
              <ToggleRow
                label="Из pending"
                checked={s.fromPending}
                onChange={(v) => patch({ fromPending: v })}
              />
            </Field>

            <div className="mt-auto space-y-3 pt-1">
              <RippleButton
                onClick={() => void save()}
                className="w-full border-primary bg-primary text-primary-foreground hover:brightness-105"
              >
                Сохранить
              </RippleButton>

              {cancels.length > 0 && (
                <div className="space-y-2 rounded-xl border border-red-200 bg-red-50/80 p-3">
                  <div className="flex items-center justify-between">
                    <div className="text-[11px] font-bold uppercase tracking-wide text-red-700">
                      Отмены списания
                    </div>
                    <RippleButton
                      onClick={() => clearCancelAlerts()}
                      rippleColor="#fecaca"
                      className="h-8 border-transparent bg-transparent px-2 text-muted-foreground hover:bg-muted"
                    >
                      ×
                    </RippleButton>
                  </div>
                  <ul className="max-h-48 space-y-2 overflow-auto">
                    {cancels.map((c) => (
                      <li
                        key={c.id}
                        className="rounded-lg border border-red-200 bg-white p-2 text-xs"
                      >
                        <div className="flex justify-between gap-2 font-semibold text-red-700">
                          <span>{c.amount || "Отмена"}</span>
                          <span className="font-mono text-muted-foreground">{c.ts}</span>
                        </div>
                        {c.card && <div className="mt-1 text-muted-foreground">Карта {c.card}</div>}
                        <div className="mt-1 font-medium">
                          {c.match_holder || c.match_label || "Сделка не найдена"}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </BentoCard>

        <BentoCard
          className="col-span-3 lg:col-span-2 lg:row-start-2"
          name="Вход"
          description="Войдите в кабинет, затем подтвердите здесь."
          tone={loginWaiting || (running && jobMode === "login") ? "active" : "default"}
          badge={
            <StepBadge n={2} active={loginWaiting || (running && jobMode === "login")} />
          }
          cta={
            <RippleButton
              disabled={running && jobMode !== "login"}
              onClick={() => void login()}
              rippleColor="#cbd5e1"
              className="border-border bg-card text-foreground hover:bg-muted/60"
            >
              Открыть вход
            </RippleButton>
          }
        >
          {loginWaiting && (
            <RippleButton
              onClick={() => void confirmLogin()}
              rippleColor="#fde68a"
              className="w-fit border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100"
            >
              Я вошёл
            </RippleButton>
          )}
        </BentoCard>

        <BentoCard
          className="col-span-3 lg:col-span-2 lg:row-start-3"
          name="Обработка и переводы"
          description="Приём сделок и переводы через телефон."
          tone={startActive || (!running && !loginWaiting) ? "active" : "default"}
          badge={<StepBadge n={3} active={startActive || (!running && !loginWaiting)} />}
          cta={
            <RippleButton
              disabled={running}
              onClick={() => void start()}
              className="border-primary bg-primary text-primary-foreground hover:brightness-105"
            >
              Запустить
            </RippleButton>
          }
        >
          <ProgressPanelView panel={pipeline} />
        </BentoCard>

        <BentoCard
          className="col-span-3 lg:col-span-2 lg:row-start-4"
          name="Чеки"
          description="После переводов загрузите чеки из папки загрузок."
          tone={receiptsWaiting ? "active" : "default"}
          muted={!receiptsWaiting && !receipts.visible}
          badge={<StepBadge n={4} active={receiptsWaiting} />}
          cta={
            <div className="flex flex-wrap gap-2">
              <RippleButton
                disabled={!receiptsWaiting}
                onClick={() => void confirmReceipts()}
                rippleColor="#fde68a"
                className="border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100"
              >
                Загрузить
              </RippleButton>
              <RippleButton
                onClick={() => void openFolder()}
                rippleColor="#cbd5e1"
                className="border-transparent bg-transparent text-muted-foreground hover:bg-muted/70"
              >
                Папка
              </RippleButton>
            </div>
          }
        >
          <p className="font-mono text-xs text-muted-foreground">{mediaDir}</p>
          <ProgressPanelView panel={receipts} />
        </BentoCard>
      </BentoGrid>
    </div>
  );
}

function StepBadge({
  n,
  tone,
  active,
}: {
  n: number;
  tone?: "ok" | "warn";
  active?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex size-7 items-center justify-center rounded-lg border font-mono text-xs font-bold",
        active
          ? "border-slate-300 bg-slate-900 text-white"
          : tone === "ok"
            ? "border-slate-400 bg-slate-700 text-white"
            : tone === "warn"
              ? "border-amber-300 bg-amber-100 text-amber-800"
              : "border-border bg-muted text-muted-foreground",
      )}
    >
      {n}
    </span>
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
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-2 rounded-xl border border-border/80 bg-muted/25 px-3 py-2.5">
      <span className="text-sm font-semibold text-foreground">{label}</span>
      <Switch checked={checked} onCheckedChange={onChange} />
    </label>
  );
}
