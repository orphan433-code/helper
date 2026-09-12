import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold transition-colors disabled:pointer-events-none disabled:opacity-45 [&_svg]:pointer-events-none [&_svg]:size-4 cursor-pointer btn-press btn-glare focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground btn-cta btn-shimmer hover:brightness-[1.03]",
        secondary:
          "bg-secondary text-secondary-foreground border border-border/50 hover:bg-foreground/[0.06]",
        outline:
          "border border-border/50 bg-background/70 text-foreground hover:bg-foreground/[0.06]",
        ghost: "text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground",
        danger:
          "bg-danger-soft text-danger border border-danger/20 hover:bg-rose-500/10",
        destructive:
          "bg-danger text-white hover:brightness-95 border-0",
        warn: "bg-amber-50 text-amber-800 border border-amber-200 hover:bg-amber-100",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 rounded-lg px-3 text-xs",
        lg: "h-11 rounded-xl px-6",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export type ButtonProps = React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
