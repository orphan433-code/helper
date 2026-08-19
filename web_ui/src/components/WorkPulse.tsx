import { OrbitingCircles } from "@/components/ui/orbiting-circles";
import { Ripple } from "@/components/ui/ripple";
import { cn } from "@/lib/utils";

export function WorkPulse({
  size = "md",
  tone = "slate",
}: {
  size?: "sm" | "md";
  tone?: "slate" | "amber" | "red";
}) {
  const compact = size === "sm";
  const outer = compact ? 11 : 42;
  const inner = compact ? 6 : 24;
  const wrap = compact ? "size-8" : "size-28";
  const dot = tone === "red" ? "bg-red-600" : tone === "amber" ? "bg-amber-500" : "bg-slate-800";
  const dotSoft =
    tone === "red" ? "bg-red-300" : tone === "amber" ? "bg-amber-300" : "bg-slate-400";

  return (
    <div className={cn("relative flex items-center justify-center", wrap)}>
      {!compact && (
        <Ripple mainCircleSize={36} numCircles={4} mainCircleOpacity={0.18} />
      )}
      <OrbitingCircles
        radius={outer}
        iconSize={compact ? 8 : 10}
        duration={compact ? 3.2 : 4.2}
        path={!compact}
      >
        <span className={cn("size-2.5 rounded-full", dot)} />
        <span className={cn("size-2 rounded-full", dotSoft)} />
        <span className={cn("size-1.5 rounded-full bg-slate-300")} />
      </OrbitingCircles>
      <OrbitingCircles
        radius={inner}
        iconSize={compact ? 6 : 8}
        duration={compact ? 5 : 6.5}
        reverse
        path={false}
      >
        <span
          className={cn(
            "size-1.5 rounded-full",
            tone === "red" ? "bg-red-400" : tone === "amber" ? "bg-amber-400" : "bg-slate-600",
          )}
        />
      </OrbitingCircles>
    </div>
  );
}
