"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * Morph between previous and current status string when `text` changes.
 * Lighter than full MorphingText loop — for status bars.
 */
export function StatusMorphText({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const [display, setDisplay] = useState(text);
  const [prev, setPrev] = useState(text);
  const [phase, setPhase] = useState<"idle" | "out" | "in">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (text === display) return;
    setPrev(display);
    setPhase("out");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setDisplay(text);
      setPhase("in");
      timer.current = setTimeout(() => setPhase("idle"), 280);
    }, 180);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [text, display]);

  return (
    <span className={cn("relative inline-block min-w-0 overflow-hidden", className)}>
      <span
        aria-hidden={phase !== "out"}
        className={cn(
          "block truncate transition-all duration-200",
          phase === "out" && "translate-y-1 opacity-0 blur-[4px]",
          phase === "in" && "translate-y-0 opacity-100 blur-0",
          phase === "idle" && "opacity-100",
          phase === "out" ? "absolute inset-0" : "sr-only",
        )}
      >
        {prev}
      </span>
      <span
          className={cn(
          "block truncate transition-all duration-300",
          phase === "out" && "translate-y-1 opacity-0 blur-[4px]",
          phase === "in" && "animate-status-morph",
        )}
      >
        {display}
      </span>
    </span>
  );
}
