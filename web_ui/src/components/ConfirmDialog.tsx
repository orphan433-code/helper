import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useConsole } from "@/store/console";

export function ConfirmDialog() {
  const dialog = useConsole((s) => s.dialog);
  const closeDialog = useConsole((s) => s.closeDialog);

  return (
    <Dialog open={dialog.open} onOpenChange={(open) => !open && closeDialog(false)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{dialog.title}</DialogTitle>
          <DialogDescription className={dialog.body ? undefined : "sr-only"}>
            {dialog.body || dialog.title}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => closeDialog(false)}>
            Назад
          </Button>
          <Button
            variant={dialog.danger ? "danger" : "default"}
            onClick={() => closeDialog(true)}
          >
            {dialog.danger ? "Подтвердить" : "OK"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
