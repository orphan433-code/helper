import { useEffect, useRef, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { ProgressPanelView } from "@/components/ProgressPanelView";
import { BlurFade } from "@/components/ui/blur-fade";
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
  const applyReceiptPreview = useConsole((st) => st.applyReceiptPreview);

  const [previewReady, setPreviewReady] = useState(0);
  const [previewAwait, setPreviewAwait] = useState(0);
  const [adbBusy, setAdbBusy] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const pollBusy = useRef(false);
  const saveTimer = useRef<number | null>(null);

  const err = (e: string) => {
    appendLog(`[ОШИБКА] ${e}`);
    void openDialog({ title: "Ошибка", body: e, danger: true, alert: true });
  };

  const checkAdb = async () => {
    if (adbBusy) return;
    setAdbBusy(true);
    try {
      await apiCall(async () => {
        const r = await api().check_adb();
        applyState({
          adb_device: r.adb_device || "не подключён",
          adb_ok: !!r.adb_ok,
        });
        return r;
      }, err);
    } finally {
      setAdbBusy(false);
    }
  };

  const save = async () => {
    if (saveState === "saving") return;
    setSaveState("saving");
    const r = await apiCall(
      () =>
        api().save_settings(
          Math.max(1, s.maxDeals || 1),
          s.minAmount.trim(),
          s.maxAmount.trim(),
          s.allowVisa,
          s.allowMastercard,
          Math.max(1, s.emptyPasses || 1),
          s.fromPending,
        ),
      err,
    );
    if (r && !r.error) {
      setSaveState("saved");
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => setSaveState("idle"), 2200);
    } else {
      setSaveState("idle");
    }
  };

  const login = () => apiCall(() => api().start_login(), err);
  const start = () =>
    apiCall(
      () =>
        api().start_pipeline(
          Math.max(1, s.maxDeals || 1),
          s.minAmount.trim(),
          s.maxAmount.trim(),
          s.allowVisa,
          s.allowMastercard,
          Math.max(1, s.emptyPasses || 1),
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
  const receiptsPhase = receipts.phase || "";
  const showReceiptPanel = receiptsWaiting || receipts.visible;
  // После старта чеков список переводов прячем (как legacy)
  const showPipelinePanel =
    pipeline.visible && !receipts.visible && !receiptsWaiting;

  useEffect(() => {
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    };
  }, []);

  useEffect(() => {
    if (
      !receiptsWaiting ||
      receiptsPhase === "processing" ||
      receiptsPhase === "done"
    ) {
      setPreviewReady(0);
      setPreviewAwait(0);
      return;
    }
    let alive = true;
    const tick = async () => {
      if (!alive || pollBusy.current) return;
      pollBusy.current = true;
      try {
        const prev = await api().preview_receipts();
        if (!alive || !prev || prev.ok === false) return;
        applyReceiptPreview(prev);
        setPreviewReady(Number(prev.ready_count || 0));
        setPreviewAwait(Number(prev.awaiting_count || 0));
      } catch {
        /* bridge ещё не готов / фаза сменилась */
      } finally {
        pollBusy.current = false;
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 2500);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [receiptsWaiting, receiptsPhase, applyReceiptPreview]);

  const loadLabel =
    receiptsWaiting && previewAwait > 0 && previewReady > 0
      ? `Загрузить (${previewReady}/${previewAwait})`
      : "Загрузить";

  return (
    <BlurFade delay={0.05} inView>
    <div className="space-y-3">
      <BentoGrid className="lg:grid-rows-[auto_auto_auto_auto]">
        <BentoCard
          className="col-span-3 lg:col-span-2 lg:row-start-1"
          name="Телефон"
          description="USB / Wi‑Fi отладка"
          tone={adbBusy ? "active" : adbOk ? "ok" : "warn"}
          badge={<StepBadge n={1} tone={adbOk ? "ok" : "warn"} active={adbBusy} />}
          cta={
            <RippleButton
              disabled={adbBusy}
              onClick={() => void checkAdb()}
              rippleColor="#cbd5e1"
              className={cn(
                "min-w-[7.5rem] border-border bg-secondary text-secondary-foreground hover:bg-slate-200/80",
                adbBusy && "opacity-90",
              )}
            >
              {adbBusy ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Проверка…
                </>
              ) : (
                "Проверить"
              )}
            </RippleButton>
          }
        >
          <div
            className={cn(
              "rounded-xl border px-3 py-2.5 transition-colors",
              adbBusy && "border-slate-300 bg-slate-50 animate-pulse",
              !adbBusy && adbOk && "border-emerald-200 bg-emerald-50/80",
              !adbBusy && !adbOk && "border-amber-200 bg-amber-50/90",
            )}
          >
            <div className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
              Устройство
            </div>
            <div className="mt-0.5 font-mono text-sm font-medium">
              {adbBusy ? "Идёт проверка ADB…" : adbText}
            </div>
          </div>
        </BentoCard>

        <BentoCard
          className="col-span-3 lg:col-span-1 lg:row-span-4 lg:row-start-1 lg:col-start-3 lg:sticky lg:top-4 lg:self-start"
          name="Фильтры"
          description="Параметры запуска"
        >
          <div className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Макс. сделок">
                <Input
                  inputMode="numeric"
                  min={1}
                  max={50}
                  value={s.maxDeals ? String(s.maxDeals) : ""}
                  onChange={(e) => {
                    const raw = e.target.value.replace(/[^\d]/g, "");
                    patch({ maxDeals: raw === "" ? 0 : Math.max(0, parseInt(raw, 10) || 0) });
                  }}
                />
              </Field>
              <Field label="Пустых проходов">
                <Input
                  inputMode="numeric"
                  min={1}
                  max={20}
                  value={s.emptyPasses ? String(s.emptyPasses) : ""}
                  onChange={(e) => {
                    const raw = e.target.value.replace(/[^\d]/g, "");
                    patch({
                      emptyPasses: raw === "" ? 0 : Math.max(0, parseInt(raw, 10) || 0),
                    });
                  }}
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

            <div className="space-y-3 pt-1">
              <RippleButton
                disabled={saveState === "saving"}
                onClick={() => void save()}
                className={cn(
                  "w-full transition-colors",
                  saveState === "saved"
                    ? "border-emerald-600 bg-emerald-600 text-white hover:bg-emerald-600"
                    : "border-primary bg-primary text-primary-foreground hover:brightness-105",
                )}
              >
                {saveState === "saving" ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Сохраняю…
                  </>
                ) : saveState === "saved" ? (
                  "Сохранено"
                ) : (
                  "Сохранить"
                )}
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
                        {c.card && (
                          <div className="mt-1 text-muted-foreground">Карта {c.card}</div>
                        )}
                        <div className="mt-1 font-medium">
                          {c.match_holder || c.match_label || "Сделка не найдена"}
                        </div>
                        {(c.match_index != null || c.match_card || c.match_amount_tjs != null) && (
                          <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                            {[
                              c.match_index != null ? `#${c.match_index}` : null,
                              c.match_card,
                              c.match_amount_tjs != null
                                ? `${c.match_amount_tjs} TJS`
                                : null,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </div>
                        )}
                        {c.balance && (
                          <div className="mt-0.5 text-[10px] text-muted-foreground">
                            Баланс {c.balance}
                          </div>
                        )}
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
          description="Войди в кабинет, затем подтверди"
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
          description="Приём сделок и переводы"
          tone={
            startActive || (!running && !loginWaiting && !receiptsWaiting)
              ? "active"
              : "default"
          }
          badge={
            <StepBadge
              n={3}
              active={startActive || (!running && !loginWaiting && !receiptsWaiting)}
            />
          }
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
          {showPipelinePanel && <ProgressPanelView panel={pipeline} mode="pipeline" />}
        </BentoCard>

        <BentoCard
          className="col-span-3 lg:col-span-2 lg:row-start-4"
          name="Чеки"
          description="Файлы с телефона, затем «Загрузить»"
          tone={receiptsWaiting || receiptsPhase === "processing" ? "active" : "default"}
          muted={!showReceiptPanel}
          badge={
            <StepBadge n={4} active={receiptsWaiting || receiptsPhase === "processing"} />
          }
          cta={
            <div className="flex flex-wrap gap-2">
              <RippleButton
                disabled={!receiptsWaiting || receiptsPhase === "processing"}
                onClick={() => void confirmReceipts()}
                rippleColor="#fde68a"
                className={cn(
                  "min-w-[8.5rem] border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100",
                  receiptsPhase === "processing" && "opacity-95",
                )}
              >
                {receiptsPhase === "processing" ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Загрузка…
                  </>
                ) : (
                  loadLabel
                )}
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
          {showReceiptPanel && <ProgressPanelView panel={receipts} mode="receipts" />}
        </BentoCard>
      </BentoGrid>
    </div>
    </BlurFade>
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
