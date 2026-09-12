import { WorkPulse } from "@/components/WorkPulse";
import { useConsole } from "@/store/console";

export function BusyOverlay() {
  const running = useConsole((s) => s.running);
  const jobMode = useConsole((s) => s.jobMode);
  const decline = useConsole((s) => s.decline);

  const opsBusy =
    running &&
    (jobMode === "redirect" ||
      jobMode === "decline" ||
      jobMode === "accept_names") &&
    decline.processing &&
    !decline.done;

  if (!opsBusy) return null;

  const isRedirect = jobMode === "redirect";
  const isAccept = jobMode === "accept_names";
  const label = isRedirect ? "Передаю" : isAccept ? "Принимаю" : "Отменяю";
  const tone = isRedirect ? "slate" : isAccept ? "slate" : "red";

  return (
    <div className="fixed inset-0 z-[35] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-foreground/25 backdrop-blur-sm animate-fade-in" />
      <div className="relative w-full max-w-sm rounded-2xl border border-border/40 bg-background/90 px-6 py-8 shadow-2xl backdrop-blur-xl animate-slide-up">
        <div className="flex flex-col items-center text-center">
          <WorkPulse size="md" tone={tone} />
          <p className="mt-4 text-[15px] font-semibold tracking-tight text-foreground">
            {label}
          </p>
          <p className="mt-1 text-sm text-foreground/55">Подожди</p>
        </div>
      </div>
    </div>
  );
}
