import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cn } from "@/lib/utils";

interface BentoGridProps extends ComponentPropsWithoutRef<"div"> {
  children: ReactNode;
}

export function BentoGrid({ children, className, ...props }: BentoGridProps) {
  return (
    <div
      className={cn("grid w-full auto-rows-[minmax(11rem,auto)] grid-cols-3 gap-4", className)}
      {...props}
    >
      {children}
    </div>
  );
}

interface BentoCardProps extends ComponentPropsWithoutRef<"div"> {
  name?: string;
  description?: string;
  Icon?: React.ElementType;
  badge?: ReactNode;
  cta?: ReactNode;
  background?: ReactNode;
  muted?: boolean;
  tone?: "default" | "ok" | "warn" | "active";
}

export function BentoCard({
  name,
  description,
  Icon,
  badge,
  cta,
  background,
  children,
  className,
  muted,
  tone = "default",
  ...props
}: BentoCardProps) {
  return (
    <div
      className={cn(
        "group relative col-span-3 flex flex-col justify-between overflow-hidden rounded-2xl",
        "bento-surface transform-gpu transition-shadow duration-300",
        muted && "[&_h3]:text-foreground/45",
        tone === "warn" && "ring-1 ring-amber-400/40",
        tone === "ok" && "ring-1 ring-ok/25",
        tone === "active" && "ring-1 ring-border",
        className,
      )}
      {...props}
    >
      {background && <div className="pointer-events-none absolute inset-0">{background}</div>}

      <div className="relative z-10 flex h-full flex-col p-4">
        {(name || Icon || cta || badge) && (
          <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 space-y-1">
              <div className="flex items-center gap-2">
                {badge}
                {Icon && (
                  <Icon className="size-5 text-foreground/55 transition-transform duration-300 group-hover:scale-90" />
                )}
                {name && (
                  <h3 className="text-base font-semibold tracking-tight text-foreground">{name}</h3>
                )}
              </div>
              {description && (
                <p className="max-w-lg text-xs text-foreground/55">{description}</p>
              )}
            </div>
            {cta && <div className="shrink-0">{cta}</div>}
          </div>
        )}
        <div className="relative z-10 flex min-h-0 flex-1 flex-col">{children}</div>
      </div>

      <div className="pointer-events-none absolute inset-0 transform-gpu transition-all duration-300 group-hover:bg-foreground/[0.015]" />
    </div>
  );
}

/** @deprecated use BentoCard */
export const BentoCell = BentoCard;
