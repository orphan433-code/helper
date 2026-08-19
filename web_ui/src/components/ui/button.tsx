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
          "bg-primary text-primary-foreground shadow-sm btn-shimmer hover:brightness-[1.03]",
        secondary:
          "bg-secondary text-secondary-foreground border border-border hover:bg-slate-200/70",
        outline:
          "border border-border bg-card text-foreground hover:bg-muted/60",
        ghost: "text-muted-foreground hover:bg-muted/70 hover:text-foreground",
        danger:
          "bg-red-50 text-red-700 border border-red-200 hover:bg-red-100",
        destructive:
          "bg-red-600 text-white hover:bg-red-700 border-0",
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
