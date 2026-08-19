import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  AlertTriangle,
  Ban,
  Check,
  Info,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

function Dialog({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root {...props} />;
}

function DialogPortal({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Portal>) {
  return <DialogPrimitive.Portal {...props} />;
}

function DialogOverlay({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      className={cn(
        "fixed inset-0 z-[100] bg-slate-900/40 backdrop-blur-[3px] animate-fade-in",
        className,
      )}
      {...props}
    />
  );
}

function DialogContent({
  className,
  children,
  showClose = true,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & {
  showClose?: boolean;
}) {
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-[101] w-[calc(100%-2rem)] max-w-md overflow-hidden rounded-2xl bg-white p-5 outline-none animate-dialog-in",
          "shadow-[0_0_0_1px_rgba(15,23,42,0.06),0_24px_48px_rgba(15,23,42,0.16)]",
          className,
        )}
        {...props}
      >
        {children}
        {showClose && (
          <DialogPrimitive.Close className="absolute right-3.5 top-3.5 rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-800 cursor-pointer">
            <X className="size-4" />
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPortal>
  );
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("flex flex-col gap-1 pr-8", className)} {...props} />;
}

function DialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      className={cn("text-[15px] font-semibold tracking-tight text-slate-900", className)}
      {...props}
    />
  );
}

function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      className={cn("text-sm leading-snug text-slate-500 whitespace-pre-wrap", className)}
      {...props}
    />
  );
}

function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div className={cn("mt-6 flex gap-2", className)} {...props} />
  );
}

export type DialogToneKind = "danger" | "ok" | "info" | "warn";

function DialogTone({ tone }: { tone: DialogToneKind }) {
  const Icon =
    tone === "danger" ? Ban : tone === "ok" ? Check : tone === "warn" ? AlertTriangle : Info;
  return (
    <span
      className={cn(
        "flex size-9 shrink-0 items-center justify-center rounded-lg",
        tone === "danger" && "bg-red-50 text-red-600",
        tone === "ok" && "bg-slate-900 text-white",
        tone === "warn" && "bg-amber-50 text-amber-700",
        tone === "info" && "bg-slate-100 text-slate-600",
      )}
    >
      <Icon className="size-5" />
    </span>
  );
}

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogTone,
};
