import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTone,
} from "@/components/ui/dialog";
import { useConsole } from "@/store/console";

export function ConfirmDialog() {
  const dialog = useConsole((s) => s.dialog);
  const closeDialog = useConsole((s) => s.closeDialog);
  const alertOnly = !!dialog.alert;
  const danger = !!dialog.danger;

  const tone = danger ? "danger" : alertOnly ? "ok" : "info";

  return (
    <Dialog open={dialog.open} onOpenChange={(open) => !open && closeDialog(false)}>
      <DialogContent>
        <div className="flex items-start gap-3.5">
          <DialogTone tone={tone} />
          <DialogHeader className="min-w-0 flex-1 pt-0.5">
            <DialogTitle>{dialog.title}</DialogTitle>
            {dialog.body ? (
              <DialogDescription className="mt-1 whitespace-pre-line">
                {dialog.body}
              </DialogDescription>
            ) : (
              <DialogDescription className="sr-only">{dialog.title}</DialogDescription>
            )}
          </DialogHeader>
        </div>
        <DialogFooter className={alertOnly ? "" : "grid grid-cols-2 gap-2"}>
          {!alertOnly && (
            <Button
              variant="outline"
              className="w-full"
              onClick={() => closeDialog(false)}
            >
              {dialog.cancelLabel || "Назад"}
            </Button>
          )}
          <Button
            variant={danger ? "danger" : "default"}
            className="w-full shadow-none"
            onClick={() => closeDialog(true)}
          >
            {alertOnly
              ? "OK"
              : dialog.confirmLabel || (danger ? "Да" : "OK")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
