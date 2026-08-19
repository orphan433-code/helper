import { WorkPulse } from "@/components/WorkPulse";
import { useConsole } from "@/store/console";

export function BusyOverlay() {
  const running = useConsole((s) => s.running);
  const jobMode = useConsole((s) => s.jobMode);
  const decline = useConsole((s) => s.decline);

  const opsBusy =
    running &&
    (jobMode === "redirect" || jobMode === "decline") &&
    decline.processing &&
    !decline.done;

  if (!opsBusy) return null;

  const isRedirect = jobMode === "redirect";

  return (
    <div className="fixed inset-0 z-[35] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-[3px] animate-fade-in" />
      <div className="relative w-full max-w-sm rounded-2xl bg-white px-6 py-8 shadow-[0_0_0_1px_rgba(15,23,42,0.06),0_24px_48px_rgba(15,23,42,0.16)] animate-slide-up">
        <div className="flex flex-col items-center text-center">
          <WorkPulse size="md" tone={isRedirect ? "slate" : "red"} />
          <p className="mt-4 text-[15px] font-semibold tracking-tight text-slate-900">
            {isRedirect ? "Передаю" : "Отменяю"}
          </p>
          <p className="mt-1 text-sm text-slate-500">Подожди</p>
        </div>
      </div>
    </div>
  );
}
