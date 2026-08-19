import { Children, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface OrbitingCirclesProps extends HTMLAttributes<HTMLDivElement> {
  className?: string;
  children?: ReactNode;
  reverse?: boolean;
  duration?: number;
  radius?: number;
  path?: boolean;
  iconSize?: number;
  speed?: number;
}

export function OrbitingCircles({
  className,
  children,
  reverse,
  duration = 20,
  radius = 160,
  path = true,
  iconSize = 30,
  speed = 1,
  ...props
}: OrbitingCirclesProps) {
  const calculatedDuration = duration / speed;
  const count = Children.count(children);
  return (
    <>
      {path && (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          version="1.1"
          className="pointer-events-none absolute inset-0 size-full"
        >
          <circle
            className="stroke-slate-300/80 stroke-1"
            cx="50%"
            cy="50%"
            r={radius}
            fill="none"
          />
        </svg>
      )}
      {Children.map(children, (child, index) => {
        const angle = (360 / Math.max(count, 1)) * index;
        return (
          <div
            style={
              {
                "--duration": calculatedDuration,
                "--radius": radius,
                "--angle": angle,
                "--icon-size": `${iconSize}px`,
              } as React.CSSProperties
            }
            className={cn(
              "animate-orbit absolute top-1/2 left-1/2 flex size-(--icon-size) transform-gpu items-center justify-center rounded-full",
              reverse && "[animation-direction:reverse]",
              className,
            )}
            {...props}
          >
            {child}
          </div>
        );
      })}
    </>
  );
}
