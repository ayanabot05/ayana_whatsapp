import { useRef, useState } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Loader2 } from "lucide-react";

/**
 * ConfirmDialog — reusable confirmation dialog for destructive actions.
 * Usage:
 *   <ConfirmDialog
 *     trigger={<button>Delete</button>}
 *     title="Are you sure?"
 *     description="This cannot be undone."
 *     confirmLabel="Delete"
 *     onConfirm={async () => { await deleteItem(); }}
 *   />
 */
export function ConfirmDialog({
  trigger,
  onConfirm,
  title = "Are you sure?",
  description = "This action cannot be undone.",
  confirmLabel = "Delete",
  variant = "danger",  // "danger" | "primary"
}) {
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef(false);
  const actionCls = variant === "danger"
    ? "bg-red-600 hover:bg-red-700 text-white"
    : "bg-ayana-primary hover:bg-ayana-primary-hover text-white";

  return (
    <AlertDialog open={open} onOpenChange={(next) => {
      if (pending.current) return;
      setError('');
      setOpen(next);
    }}>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel data-testid="confirm-cancel" disabled={busy}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            data-testid="confirm-action"
            disabled={busy}
            className={actionCls}
            onClick={async (e) => {
              e.preventDefault();
              if (pending.current) return;
              pending.current = true;
              setError('');
              setBusy(true);
              try {
                await onConfirm();
                setOpen(false);
              } catch {
                setError('The action could not be completed. Please try again.');
              } finally {
                pending.current = false;
                setBusy(false);
              }
            }}
          >
            {busy && <Loader2 className="w-4 h-4 animate-spin mr-2" />}
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
