import { AgentCommandBar } from "@/components/AgentCommandBar";

export function AgentView() {
  return (
    <div className="flex min-h-[calc(100vh-11rem)] items-center justify-center py-6">
      <div className="w-full">
        <AgentCommandBar />
      </div>
    </div>
  );
}
