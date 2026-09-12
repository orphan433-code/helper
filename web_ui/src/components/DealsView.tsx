import { useState } from "react";
import { BlurFade } from "@/components/ui/blur-fade";
import { Input } from "@/components/ui/input";
import { BentoCard, BentoGrid } from "@/components/ui/bento-grid";
import { RippleButton } from "@/components/ui/ripple-button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  CollapsibleBlock,
  Field,
  FilterChip,
  FilterChipRow,
  Segmented,
} from "@/components/filters";
import { bankFilterHint, BinPicker } from "@/components/BinPicker";
import { api, apiCall, serverPost } from "@/lib/api";
import { EXTRA_REDIRECT_BINS } from "@/lib/bankBins";
import { TRADERS } from "@/lib/types";
import { useConsole } from "@/store/console";
import {
  buildUiContext,
  CommandPreviewPanel,
  type AgentPlan,
  type AgentPreview,
} from "@/components/CommandPreview";

function optAmount(raw: string): number | null {
  const t = raw.trim().replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

type OpsPending = {
  kind: "redirect" | "decline";
  status?: string;
  bins: string[];
  maxN: number;
  mcOnly?: boolean;
};

export function DealsView() {
  const s = useConsole((st) => st.settings);
  const patch = useConsole((st) => st.patchSettings);
  const running = useConsole((st) => st.running);
  const jobMode = useConsole((st) => st.jobMode);
  const loginHzOk = useConsole((st) => st.loginHzOk);
  const loginEzeOk = useConsole((st) => st.loginEzeOk);
  const appendLog = useConsole((st) => st.appendLog);
  const openDialog = useConsole((st) => st.openDialog);
  const clearDeclineResult = useConsole((st) => st.clearDeclineResult);

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewBusy, setPreviewBusy] = useState<"preview" | "execute" | null>(null);
  const [plan, setPlan] = useState<AgentPlan | null>(null);
  const [preview, setPreview] = useState<AgentPreview | null>(null);
  const [pending, setPending] = useState<OpsPending | null>(null);
  const [redirBanksOpen, setRedirBanksOpen] = useState(false);
  const [declineBanksOpen, setDeclineBanksOpen] = useState(false);

  const err = (e: string) => {
    appendLog(`[ОШИБКА] ${e}`);
    void openDialog({ title: "Ошибка", body: e, danger: true, alert: true });
  };

  const opsBusy = running && (jobMode === "redirect" || jobMode === "decline");
  const previewing = previewOpen || !!previewBusy;
  const selectedLabels = TRADERS.filter((t) => s.redirAccounts[t.id]).map((t) => t.label);
  const selectedTraders = TRADERS.filter((t) => s.redirAccounts[t.id]).map((t) => t.traderId);

  const extraRedirect = [...EXTRA_REDIRECT_BINS];
  const redirectCatalog = [...new Set([...s.redirectBinList, ...extraRedirect])];

  const patchRedirectBins = (next: Record<string, boolean>) => patch({ redirectBins: next });
  const patchDeclineBins = (next: Record<string, boolean>) => patch({ declineBins: next });

  const setDeclineService = async (next: "hz" | "eze") => {
    if (opsBusy || next === s.declineService) return;
    const prev = s.declineService;
    patch({ declineService: next });
    const result = await apiCall(() => api().save_decline_service(next), err);
    if (result && typeof result.error === "string" && result.error) {
      patch({ declineService: prev });
    }
  };

  const closePreview = () => {
    if (previewBusy === "execute") return;
    setPreviewOpen(false);
    setPreviewBusy(null);
    setPlan(null);
    setPreview(null);
    setPending(null);
  };

  const saveFilters = () => {
    const bins = redirectCatalog.filter((p) => s.redirectBins[p]);
    return apiCall(
      () =>
        api().save_redirect_filters(
          s.redirSkipBog,
          s.redirVisaOnly,
          s.redirMaxRemaining,
          bins,
        ),
      err,
    );
  };

  const showPreview = async (nextPlan: AgentPlan, nextPending: OpsPending) => {
    setPending(nextPending);
    setPlan(nextPlan);
    setPreview(null);
    setPreviewOpen(true);
    setPreviewBusy("preview");
    try {
      const prev = (await serverPost("/api/agent/preview", {
        plan: nextPlan,
        ui_context: buildUiContext(s),
      })) as AgentPreview;
      if (prev?.error) {
        setPreviewOpen(false);
        setPlan(null);
        setPreview(null);
        setPending(null);
        err(String(prev.error));
        return;
      }
      setPlan((prev.plan as AgentPlan) || nextPlan);
      setPreview(prev);
    } catch (e) {
      setPreviewOpen(false);
      setPlan(null);
      setPreview(null);
      setPending(null);
      err(String(e));
    } finally {
      setPreviewBusy((cur) => (cur === "preview" ? null : cur));
    }
  };

  const redirect = async (status: string) => {
    if (opsBusy || previewing) return;
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
    const bins = redirectCatalog.filter((p) => s.redirectBins[p]);
    await showPreview(
      {
        action: "redirect",
        deal_status: status,
        max_per_run: maxN,
        min_amount: optAmount(s.redirMin),
        max_amount: optAmount(s.redirMaxAmt),
        skip_bog: s.redirSkipBog,
        visa_only: s.redirVisaOnly,
        max_remaining: s.redirMaxRemaining,
        redirect_bins: bins,
        trader_ids: selectedTraders,
        trader_labels: selectedLabels,
      },
      { kind: "redirect", status, bins, maxN },
    );
  };

  const declineRun = async () => {
    if (opsBusy || previewing) return;
    const mcOnly = !!s.declineMastercardOnly;
    const bins = mcOnly ? [] : s.declineBinList.filter((p) => s.declineBins[p]);
    if (!mcOnly && !bins.length) {
      await openDialog({
        title: "Отмена",
        body: "Включи хотя бы один BIN или «Только MC»",
        alert: true,
      });
      return;
    }
    const maxN = parseInt(String(s.declineMax).trim(), 10);
    if (!Number.isFinite(maxN) || maxN < 1) {
      await openDialog({
        title: "Отмена",
        body: "Укажи количество (1–50)",
        alert: true,
      });
      return;
    }
    const take = Math.min(50, maxN);
    await showPreview(
      {
        action: "decline",
        max_per_run: take,
        min_amount: optAmount(s.declineMinAmt),
        max_amount: optAmount(s.declineMaxAmt),
        decline_bins: bins,
        mastercard_only: mcOnly,
        service: s.declineService,
      },
      { kind: "decline", bins, maxN: take, mcOnly },
    );
  };

  const confirmPreview = async () => {
    if (!pending || running) return;
    setPreviewBusy("execute");
    clearDeclineResult();
    try {
      if (pending.kind === "redirect") {
        await apiCall(async () => {
          await saveFilters();
          return api().start_redirect(
            selectedTraders,
            pending.maxN,
            s.redirMin || null,
            s.redirMaxAmt || null,
            pending.status || "new",
            s.redirSkipBog,
            s.redirVisaOnly,
            s.redirMaxRemaining,
            pending.bins,
          );
        }, err);
      } else {
        await apiCall(
          () =>
            api().start_decline(
              [...pending.bins],
              false,
              pending.maxN,
              s.declineMinAmt.trim() || null,
              s.declineMaxAmt.trim() || null,
              !!pending.mcOnly,
              s.declineService,
            ),
          err,
        );
      }
      setPreviewOpen(false);
      setPlan(null);
      setPreview(null);
      setPending(null);
    } finally {
      setPreviewBusy(null);
    }
  };

  const redirHint = bankFilterHint(s.redirectBins, redirectCatalog, extraRedirect);
  const declineHint = s.declineMastercardOnly
    ? "только Mastercard"
    : bankFilterHint(s.declineBins, s.declineBinList);

  return (
    <BlurFade delay={0.05} inView>
      {previewOpen ? (
        <div className="relative mx-auto w-full max-w-[42rem]">
          <BentoGrid className="w-full lg:grid-rows-[auto]">
            <div className="col-span-3">
              <CommandPreviewPanel
                plan={plan}
                preview={preview}
                busy={previewBusy}
                loading={previewBusy === "preview" && !preview}
                disabled={opsBusy}
                onConfirm={() => void confirmPreview()}
                onCancel={closePreview}
                cancelLabel="Назад"
              />
            </div>
          </BentoGrid>
        </div>
      ) : (
        <Tabs defaultValue="redirect">
          <TabsList className="w-full sm:w-auto">
            <TabsTrigger value="redirect" className="flex-1 sm:flex-none">
              Редирект
            </TabsTrigger>
            <TabsTrigger value="decline" className="flex-1 sm:flex-none">
              Отмена
            </TabsTrigger>
          </TabsList>

          <TabsContent value="redirect">
            <BentoCard className="col-span-3" name="Редирект">
              <div className="flex flex-col gap-3">
                <FilterChipRow>
                  {TRADERS.map((t) => (
                    <FilterChip
                      key={t.id}
                      label={t.label}
                      active={!!s.redirAccounts[t.id]}
                      disabled={opsBusy}
                      onClick={() =>
                        patch({
                          redirAccounts: {
                            ...s.redirAccounts,
                            [t.id]: !s.redirAccounts[t.id],
                          },
                        })
                      }
                    />
                  ))}
                </FilterChipRow>

                <div className="grid gap-3 sm:grid-cols-3">
                  <Field label="Сделок">
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

                <FilterChipRow>
                  <FilterChip
                    label="без BoG"
                    active={s.redirSkipBog}
                    disabled={opsBusy}
                    onClick={() => patch({ redirSkipBog: !s.redirSkipBog })}
                  />
                  <FilterChip
                    label="Visa"
                    active={s.redirVisaOnly}
                    disabled={opsBusy}
                    onClick={() => patch({ redirVisaOnly: !s.redirVisaOnly })}
                  />
                  <FilterChip
                    label="< 1 ч"
                    active={s.redirMaxRemaining}
                    disabled={opsBusy}
                    onClick={() => patch({ redirMaxRemaining: !s.redirMaxRemaining })}
                  />
                </FilterChipRow>

                <CollapsibleBlock
                  open={redirBanksOpen}
                  onOpenChange={setRedirBanksOpen}
                  title="Банки"
                  hint={redirHint}
                  disabled={opsBusy}
                >
                  <BinPicker
                    selected={s.redirectBins}
                    disabled={opsBusy}
                    extra={extraRedirect}
                    onChange={patchRedirectBins}
                  />
                </CollapsibleBlock>

                <div className="grid grid-cols-2 gap-2 pt-1">
                  <RippleButton
                    disabled={opsBusy || previewing}
                    onClick={() => void redirect("new")}
                    className="btn-cta h-12 border-primary bg-primary text-base text-primary-foreground hover:brightness-105"
                  >
                    NEW
                  </RippleButton>
                  <RippleButton
                    disabled={opsBusy || previewing}
                    onClick={() => void redirect("pending")}
                    rippleColor="#e7e2d9"
                    className="h-12 border-border/50 bg-background/70 text-base text-foreground shadow-sm hover:bg-foreground/[0.06]"
                  >
                    PENDING
                  </RippleButton>
                </div>
              </div>
            </BentoCard>
          </TabsContent>

          <TabsContent value="decline">
            <BentoCard className="col-span-3" name="Отмена">
              <div className="flex flex-col gap-3">
                <Field label="Сервис">
                  <Segmented
                    value={s.declineService}
                    disabled={opsBusy}
                    onChange={(id) => void setDeclineService(id)}
                    options={[
                      {
                        id: "hz" as const,
                        label: "HZ",
                        hint: loginHzOk ? " · онлайн" : "",
                      },
                      {
                        id: "eze" as const,
                        label: "Easy",
                        hint: loginEzeOk ? " · онлайн" : "",
                      },
                    ]}
                  />
                </Field>

                <div className="grid gap-3 sm:grid-cols-3">
                  <Field label="Сделок">
                    <Input
                      inputMode="numeric"
                      min={1}
                      max={50}
                      value={s.declineMax}
                      placeholder="1–50"
                      disabled={opsBusy}
                      onChange={(e) =>
                        patch({
                          declineMax: e.target.value.replace(/[^\d]/g, "").slice(0, 2),
                        })
                      }
                    />
                  </Field>
                  <Field label="От">
                    <Input
                      value={s.declineMinAmt}
                      placeholder="USDT"
                      disabled={opsBusy}
                      onChange={(e) => patch({ declineMinAmt: e.target.value })}
                    />
                  </Field>
                  <Field label="До">
                    <Input
                      value={s.declineMaxAmt}
                      placeholder="USDT"
                      disabled={opsBusy}
                      onChange={(e) => patch({ declineMaxAmt: e.target.value })}
                    />
                  </Field>
                </div>

                <FilterChipRow>
                  <FilterChip
                    label="только MC"
                    active={s.declineMastercardOnly}
                    disabled={opsBusy}
                    onClick={() =>
                      patch({ declineMastercardOnly: !s.declineMastercardOnly })
                    }
                  />
                </FilterChipRow>

                <CollapsibleBlock
                  open={declineBanksOpen}
                  onOpenChange={setDeclineBanksOpen}
                  title="Банки"
                  hint={declineHint}
                  disabled={opsBusy || s.declineMastercardOnly}
                >
                  <BinPicker
                    selected={s.declineBins}
                    disabled={opsBusy || s.declineMastercardOnly}
                    onChange={patchDeclineBins}
                  />
                </CollapsibleBlock>

                <RippleButton
                  disabled={opsBusy || previewing}
                  onClick={() => void declineRun()}
                  className="btn-cta h-12 w-full border-danger bg-danger text-base text-white hover:brightness-95"
                  rippleColor="#fecaca"
                >
                  Отменить
                </RippleButton>
              </div>
            </BentoCard>
          </TabsContent>
        </Tabs>
      )}
    </BlurFade>
  );
}
