import { useEffect, useState } from "react";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

function actionTitle(action: string) {
  if (action === "duplicate") return "Duplicate model";
  if (action === "rename") return "Rename model";
  if (action === "delete") return "Delete model";
  return "Model action";
}

type ModelActionDialogProps = {
  dialog: {
    action: "duplicate" | "rename" | "delete";
    model: { name: string };
    defaultValue?: string;
  } | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (value: string) => void;
};

export default function ModelActionDialog({ dialog, busy, onCancel, onConfirm }: ModelActionDialogProps) {
  const [value, setValue] = useState("");

  useEffect(() => {
    setValue(dialog?.defaultValue ?? "");
  }, [dialog]);

  const requiresName = dialog?.action === "duplicate" || dialog?.action === "rename";
  const trimmedValue = value.trim();
  const canConfirm = !busy && (!requiresName || Boolean(trimmedValue));

  return (
    <Dialog open={Boolean(dialog)} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent>
        {dialog && (
          <>
            <DialogHeader>
              <DialogTitle>{actionTitle(dialog.action)}</DialogTitle>
              <DialogDescription>
                {dialog.action === "delete"
                  ? `Delete “${dialog.model.name}” from local browser storage.`
                  : "Choose the model name to store in the saved model list."}
              </DialogDescription>
            </DialogHeader>

            {dialog.action === "delete" ? (
              <p className="text-sm text-muted-foreground">
                Are you sure you want to delete model <strong className="text-foreground">{dialog.model.name}</strong>?
              </p>
            ) : (
              <div className="space-y-1.5">
                <Label htmlFor="model-action-name">Model name</Label>
                <Input
                  id="model-action-name"
                  type="text"
                  autoFocus
                  value={value}
                  disabled={busy}
                  onChange={(event) => setValue(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && canConfirm) {
                      onConfirm(trimmedValue);
                    }
                  }}
                />
              </div>
            )}

            <DialogFooter>
              <Button type="button" variant="outline" disabled={busy} onClick={onCancel}>
                Cancel
              </Button>
              <Button
                type="button"
                variant={dialog.action === "delete" ? "destructive" : "default"}
                disabled={!canConfirm}
                onClick={() => onConfirm(trimmedValue)}
              >
                {dialog.action === "delete" ? "Delete model" : "Save"}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
