import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { ProgressPanelView } from "@/components/ProgressPanelView";
import { BlurFade } from "@/components/ui/blur-fade";
import { Input } from "@/components/ui/input";
import { BentoCard, BentoGrid } from "@/components/ui/bento-grid";
import { RippleButton } from "@/components/ui/ripple-button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
  FilterBar,
  FilterChip,
  FilterChipRow,
  FilterSection,
  Segmented,
  ToggleRow,
} from "@/components/filters";
import { EXTRA_REDIRECT_BINS } from "@/lib/bankBins";
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
  const loginHzOk = useConsole((st) => st.loginHzOk);
  const loginEzeOk = useConsole((st) => st.loginEzeOk);
  const loginTarget = useConsole((st) => st.loginTarget);
  const mediaDir = useConsole((st) => st.mediaDir);
  const pipeline = useConsole((st) => st.pipeline);
  const receipts = useConsole((st) => st.receipts);
  const cancels = useConsole((st) => st.cancels);
  const appendLog = useConsole((st) => st.appendLog);
  const openDialog = useConsole((st) => st.openDialog);
  const clearCancelAlerts = useConsole((st) => st.clearCancelAlerts);
  const applyState = useConsole((st) => st.applyState);
  const applyReceiptPreview = useConsole((st) => st.applyReceiptPreview);

  const [adbBusy, setAdbBusy] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const pollBusy = useRef(false);
  const saveTimer = useRef<number | null>(null);

  const awaitingReceipts = receipts.deals.filter(
    (d) => d.state === "pending" || d.state === "matched",
  ).length;
  const readyReceipts = receipts.deals.filter(
    (d) =>
      d.preview_ready ||
      (d.has_shot && (!d.needs_video || d.has_video)),
  ).length;

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
    const pipelineBins = uhodyatBinCodes(s.pipelineBinList).filter(
      (p) => s.pipelineBins[p],
    );
    const selectedCurrencies = s.currencyList.filter((c) => s.currencies[c]);
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
          pipelineBins,
          selectedCurrencies,
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

  const login = (service: "hz" | "eze") =>
    apiCall(() => api().start_login(service), err);
  const setPipelineService = async (next: "hz" | "eze") => {
    if (running || next === s.pipelineService) return;
    const prev = s.pipelineService;
    patch({ pipelineService: next });
    const result = await apiCall(() => api().save_pipeline_service(next), err);
    if (result && typeof result.error === "string" && result.error) {
      patch({ pipelineService: prev });
    }
  };
  const setSkipTbc = async (next: boolean) => {
    if (running || next === s.skipTbc) return;
    const prev = s.skipTbc;
    patch({ skipTbc: next });
    const result = await apiCall(() => api().save_pipeline_skip_tbc(next), err);
    if (result && typeof result.error === "string" && result.error) {
      patch({ skipTbc: prev });
    }
  };
  const setSkipBog = async (next: boolean) => {
    if (running || next === s.skipBog) return;
    const prev = s.skipBog;
    patch({ skipBog: next });
    const result = await apiCall(() => api().save_pipeline_skip_bog(next), err);
    if (result && typeof result.error === "string" && result.error) {
      patch({ skipBog: prev });
    }
  };
  const start = async () => {
    const deals = Math.max(1, Math.min(50, s.maxDeals || 0));
    if (!s.maxDeals || s.maxDeals < 1) {
      await openDialog({
        title: "Запуск",
        body: "Укажи сколько сделок (1–50)",
        alert: true,
      });
      return;
    }
    const pipelineBins = uhodyatBinCodes(s.pipelineBinList).filter(
      (p) => s.pipelineBins[p],
    );
    const selectedCurrencies = s.currencyList.filter((c) => s.currencies[c]);
    return apiCall(
      () =>
        api().start_pipeline(
          deals,
          s.minAmount.trim(),
          s.maxAmount.trim(),
          s.allowVisa,
          s.allowMastercard,
          Math.max(1, s.emptyPasses || 1),
          s.fromPending,
          pipelineBins,
          selectedCurrencies,
          s.pipelineService,
        ),
      err,
    );
  };
  const hideConfirmPrompt = useConsole((st) => st.hideConfirmPrompt);
  const confirmLogin = () => {
    hideConfirmPrompt();
    return apiCall(() => api().confirm("login"), err);
  };
  const confirmReceipts = () => {
    hideConfirmPrompt();
    return apiCall(() => api().confirm("receipts"), err);
  };
  const openFolder = () => apiCall(() => api().open_videos_folder(), err);

  const loginWaiting = running && jobMode === "login";
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
    const previewActive =
      showReceiptPanel &&
      receiptsPhase !== "processing" &&
      receiptsPhase !== "done" &&
      awaitingReceipts > 0;
    if (!previewActive) return;
    let alive = true;
    const tick = async () => {
      if (!alive || pollBusy.current) return;
      pollBusy.current = true;
      try {
        const prev = await api().preview_receipts();
        if (!alive || !prev || prev.ok === false) return;
        applyReceiptPreview(prev);
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
  }, [showReceiptPanel, receiptsPhase, awaitingReceipts, applyReceiptPreview]);

  const loadLabel =
    receiptsWaiting && awaitingReceipts > 0 && readyReceipts > 0
      ? `Загрузить ${readyReceipts}/${awaitingReceipts}`
      : "Загрузить";

  const hz = s.pipelineService !== "eze";
  const uhodyatBins = uhodyatBinCodes(s.pipelineBinList);
  const filterFacts = pipelineFacts(s, hz, uhodyatBins);

  return (
    <BlurFade delay={0.05} inView>
      <div className="space-y-3">
        <BentoGrid className="auto-rows-auto lg:grid-rows-[auto]">
          <BentoCard
            className="col-span-3 lg:col-span-1"
            name="Телефон"
            tone={adbBusy ? "active" : adbOk ? "ok" : "warn"}
            badge={<StepBadge n={1} tone={adbOk ? "ok" : "warn"} active={adbBusy} />}
            cta={
              <RippleButton
                disabled={adbBusy}
                onClick={() => void checkAdb()}
                rippleColor="#e7e2d9"
                className={cn(
                  "min-w-[6.5rem] border-border/50 bg-background/70 text-foreground hover:bg-foreground/[0.06]",
                  adbBusy && "opacity-90",
                )}
              >
                {adbBusy ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    …
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
                adbBusy && "animate-pulse border-foreground/[0.08] bg-white/80",
                !adbBusy && adbOk && "border-foreground/[0.08] bg-white/90",
                !adbBusy && !adbOk && "border-amber-500/25 bg-amber-50/80",
              )}
            >
              <div className="font-mono text-sm font-medium">
                {adbBusy ? "Проверяю…" : adbText}
              </div>
            </div>
          </BentoCard>

          <BentoCard
            className="col-span-3 lg:col-span-2"
            name="Вход"
            tone={loginWaiting || (running && jobMode === "login") ? "active" : "default"}
            badge={
              <StepBadge n={2} active={loginWaiting || (running && jobMode === "login")} />
            }
          >
            <div className="grid grid-cols-2 gap-2">
              {(
                [
                  ["hz", "HZ", "HZ", loginHzOk],
                  ["eze", "Easy", "EZ", loginEzeOk],
                ] as const
              ).map(([id, label, mark, ok]) => (
                <HostTile
                  key={id}
                  mark={mark}
                  label={label}
                  ok={ok}
                  waiting={loginWaiting && loginTarget === id}
                  disabled={running && !(loginWaiting && loginTarget === id)}
                  onClick={() =>
                    void (loginWaiting && loginTarget === id
                      ? confirmLogin()
                      : login(id))
                  }
                />
              ))}
            </div>
          </BentoCard>

          <BentoCard
            className="col-span-3"
            name="Переводы"
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
          >
            <div className="flex flex-col gap-3">
              <Field label="Сервис">
                <Segmented
                  value={s.pipelineService}
                  disabled={running}
                  onChange={(id) => void setPipelineService(id)}
                  options={[
                    { id: "hz" as const, label: "HZ" },
                    { id: "eze" as const, label: "Easy" },
                  ]}
                />
              </Field>

              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Сделок">
                  <Input
                    inputMode="numeric"
                    min={1}
                    max={50}
                    value={s.maxDeals ? String(s.maxDeals) : ""}
                    onChange={(e) => {
                      const raw = e.target.value.replace(/[^\d]/g, "");
                      patch({
                        maxDeals: raw === "" ? 0 : Math.max(0, parseInt(raw, 10) || 0),
                      });
                    }}
                  />
                </Field>
                <Field label="Сумма от">
                  <Input
                    placeholder="USDT"
                    value={s.minAmount}
                    onChange={(e) => patch({ minAmount: e.target.value })}
                  />
                </Field>
                <Field label="до">
                  <Input
                    placeholder="USDT"
                    value={s.maxAmount}
                    onChange={(e) => patch({ maxAmount: e.target.value })}
                  />
                </Field>
              </div>

              <FilterBar
                facts={filterFacts}
                disabled={running}
                onEdit={() => setFiltersOpen(true)}
              />

              <RippleButton
                disabled={running}
                onClick={() => void start()}
                className="btn-cta h-12 w-full border-primary bg-primary text-base text-primary-foreground hover:brightness-105"
              >
                Запустить
              </RippleButton>

              {showPipelinePanel && <ProgressPanelView panel={pipeline} mode="pipeline" />}

              {cancels.length > 0 && (
                <div className="space-y-2 rounded-xl border border-danger/20 bg-danger-soft/80 p-3">
                  <div className="flex items-center justify-between">
                    <div className="text-xs font-semibold text-danger">Отмены списания</div>
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
                        className="rounded-lg border border-danger/20 bg-background/80 p-2 text-xs"
                      >
                        <div className="flex justify-between gap-2 font-semibold text-danger">
                          <span>{c.amount || "Отмена"}</span>
                          <span className="font-mono text-muted-foreground">{c.ts}</span>
                        </div>
                        {c.card && (
                          <div className="mt-1 text-muted-foreground">Карта {c.card}</div>
                        )}
                        <div className="mt-1 font-medium">
                          {c.match_holder || c.match_label || "Сделка не найдена"}
                        </div>
                        {(c.match_index != null ||
                          c.match_card ||
                          c.match_amount_tjs != null) && (
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
          </BentoCard>

          <BentoCard
            className="col-span-3"
            name="Чеки"
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
                    receiptsWaiting && receiptsPhase !== "processing" && "h-11 font-bold",
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
                  rippleColor="#e7e2d9"
                  className="border-transparent bg-transparent text-muted-foreground hover:bg-muted/70"
                >
                  Папка
                </RippleButton>
              </div>
            }
          >
            {showReceiptPanel && (
              <p className="mb-2 font-mono text-xs text-muted-foreground">{mediaDir}</p>
            )}
            {showReceiptPanel && <ProgressPanelView panel={receipts} mode="receipts" />}
            {!showReceiptPanel && (
              <p className="text-sm text-muted-foreground">Появятся после переводов</p>
            )}
          </BentoCard>
        </BentoGrid>

        <Dialog open={filtersOpen} onOpenChange={setFiltersOpen}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>Фильтры</DialogTitle>
            </DialogHeader>
            <div className="mt-4 flex max-h-[min(70vh,32rem)] flex-col gap-4 overflow-y-auto pr-0.5">
              <FilterSection label="Карты">
                <FilterChipRow>
                  <FilterChip
                    label="Visa"
                    active={s.allowVisa}
                    onClick={() => patch({ allowVisa: !s.allowVisa })}
                  />
                  <FilterChip
                    label="Mastercard"
                    active={s.allowMastercard}
                    onClick={() => patch({ allowMastercard: !s.allowMastercard })}
                  />
                </FilterChipRow>
              </FilterSection>
              <FilterSection label="Банки">
                <FilterChipRow>
                  <FilterChip
                    label="пропуск TBC"
                    tone="warn"
                    active={s.skipTbc}
                    disabled={running}
                    onClick={() => void setSkipTbc(!s.skipTbc)}
                  />
                  <FilterChip
                    label="пропуск BOG"
                    tone="warn"
                    active={s.skipBog}
                    disabled={running}
                    onClick={() => void setSkipBog(!s.skipBog)}
                  />
                </FilterChipRow>
              </FilterSection>
              <FilterSection label="Уходят">
                <FilterChipRow>
                  {uhodyatBins.map((bin) => (
                    <FilterChip
                      key={bin}
                      label={`только ${bin}`}
                      active={!!s.pipelineBins[bin]}
                      onClick={() =>
                        patch({
                          pipelineBins: {
                            ...s.pipelineBins,
                            [bin]: !s.pipelineBins[bin],
                          },
                        })
                      }
                    />
                  ))}
                </FilterChipRow>
              </FilterSection>
              {hz && (
                <>
                  <FilterSection label="Валюта">
                    <FilterChipRow>
                      {s.currencyList.map((code) => (
                        <FilterChip
                          key={code}
                          label={code}
                          active={!!s.currencies[code]}
                          onClick={() =>
                            patch({
                              currencies: { ...s.currencies, [code]: !s.currencies[code] },
                            })
                          }
                        />
                      ))}
                    </FilterChipRow>
                  </FilterSection>
                  <ToggleRow
                    label="Только pending"
                    checked={s.fromPending}
                    onChange={(v) => patch({ fromPending: v })}
                  />
                </>
              )}
              <Field label="Пустых проходов подряд">
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
              <RippleButton
                disabled={saveState === "saving"}
                onClick={() => void save()}
                className={cn(
                  "w-full transition-colors",
                  saveState === "saved"
                    ? "border-ok bg-ok text-white hover:bg-ok"
                    : "border-border/50 bg-background/70 text-foreground hover:bg-foreground/[0.06]",
                )}
              >
                {saveState === "saving" ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Сохраняю…
                  </>
                ) : saveState === "saved" ? (
                  "Запомнено"
                ) : (
                  "Запомнить"
                )}
              </RippleButton>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </BlurFade>
  );
}

function uhodyatBinCodes(list: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const prefix of [...EXTRA_REDIRECT_BINS, ...list]) {
    if (prefix && !seen.has(prefix)) {
      seen.add(prefix);
      out.push(prefix);
    }
  }
  return out;
}

function pipelineFacts(
  s: ReturnType<typeof useConsole.getState>["settings"],
  hz: boolean,
  uhodyatBins: string[],
): { label: string; value: string }[] {
  const facts: { label: string; value: string }[] = [];

  if (s.allowVisa && s.allowMastercard) facts.push({ label: "карты", value: "Visa и MC" });
  else if (s.allowVisa) facts.push({ label: "карты", value: "Visa" });
  else if (s.allowMastercard) facts.push({ label: "карты", value: "MC" });
  else facts.push({ label: "карты", value: "не выбраны" });

  if (s.skipTbc && s.skipBog) facts.push({ label: "банки", value: "пропуск TBC и BOG" });
  else if (s.skipTbc) facts.push({ label: "банки", value: "пропуск TBC" });
  else if (s.skipBog) facts.push({ label: "банки", value: "пропуск BOG" });
  else facts.push({ label: "банки", value: "все" });

  const onlyBins = uhodyatBins.filter((p) => s.pipelineBins[p]);
  if (onlyBins.length) {
    facts.push({ label: "BIN", value: `только ${onlyBins.join(", ")}` });
  }

  if (hz) {
    const cur = s.currencyList.filter((c) => s.currencies[c]);
    if (cur.length) facts.push({ label: "валюта", value: cur.join(", ") });
    if (s.fromPending) facts.push({ label: "режим", value: "pending" });
  }
  if (s.emptyPasses !== 2) {
    facts.push({ label: "пустые", value: String(s.emptyPasses) });
  }
  return facts;
}

function HostTile({
  mark,
  label,
  ok,
  waiting,
  disabled,
  onClick,
}: {
  mark: string;
  label: string;
  ok: boolean;
  waiting: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "group flex min-h-[7.5rem] flex-col items-start justify-between rounded-2xl border p-3.5 text-left transition-all duration-150",
        waiting &&
          "border-amber-400/55 bg-amber-50/90 shadow-[0_1px_2px_rgba(180,83,9,0.12)]",
        !waiting &&
          ok &&
          "border-emerald-500/20 bg-white/90 hover:border-emerald-500/40 hover:bg-white",
        !waiting &&
          !ok &&
          "border-foreground/[0.08] bg-white/80 hover:border-foreground/15 hover:bg-white",
        disabled && "cursor-not-allowed opacity-50",
        !disabled && "cursor-pointer",
      )}
    >
      <div className="flex w-full items-center justify-between gap-2">
        <span
          className={cn(
            "flex size-9 items-center justify-center rounded-xl text-[11px] font-bold tracking-[0.08em]",
            waiting && "bg-amber-100 text-amber-900",
            !waiting && ok && "bg-emerald-500/10 text-emerald-800",
            !waiting && !ok && "bg-foreground/[0.05] text-foreground/70",
          )}
        >
          {mark}
        </span>
        {waiting ? (
          <Loader2 className="size-4 animate-spin text-amber-700" />
        ) : ok ? (
          <span className="relative flex size-2.5">
            <span className="absolute inset-0 animate-ping rounded-full bg-emerald-400/80 motion-reduce:animate-none" />
            <span className="relative size-2.5 rounded-full bg-emerald-500" />
          </span>
        ) : (
          <span className="size-2.5 rounded-full bg-foreground/18" />
        )}
      </div>
      <div className="mt-3 min-w-0">
        <p className="text-sm font-semibold tracking-tight text-foreground">{label}</p>
        <p
          className={cn(
            "mt-0.5 text-xs font-medium",
            waiting && "text-amber-800",
            !waiting && ok && "text-emerald-700",
            !waiting && !ok && "text-foreground/45",
          )}
        >
          {waiting ? "Жду вход" : ok ? "Онлайн" : "Нет сессии"}
        </p>
      </div>
      <span
        className={cn(
          "mt-3 text-[11px] font-semibold",
          waiting && "text-amber-900",
          !waiting && "text-foreground/40 group-hover:text-foreground/70",
        )}
      >
        {waiting ? "Я вошёл" : ok ? "Войти снова" : "Войти"}
      </span>
    </button>
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
          ? "border-border/50 bg-primary text-primary-foreground"
          : tone === "ok"
            ? "border-border/40 bg-primary/80 text-primary-foreground"
            : tone === "warn"
              ? "border-amber-300 bg-amber-100 text-amber-800"
              : "border-border bg-muted text-muted-foreground",
      )}
    >
      {n}
    </span>
  );
}
