"use client";

import { useEffect, useRef } from "react";

export function ConfirmationDialog({
  title,
  description,
  confirmLabel,
  destructive = false,
  busy,
  onCancel,
  onConfirm,
}: {
  title: string;
  description: React.ReactNode;
  confirmLabel: string;
  destructive?: boolean;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    dialog.showModal();
    cancelRef.current?.focus();
    const cancel = (event: Event) => {
      event.preventDefault();
      if (!busy) onCancel();
    };
    dialog.addEventListener("cancel", cancel);
    return () => {
      dialog.removeEventListener("cancel", cancel);
      if (dialog.open) dialog.close();
    };
  }, [busy, onCancel]);

  return (
    <dialog
      ref={dialogRef}
      className="universe-dialog"
      aria-labelledby="universe-dialog-title"
      aria-describedby="universe-dialog-description"
    >
      <h2 id="universe-dialog-title">{title}</h2>
      <div id="universe-dialog-description">{description}</div>
      <div className="universe-dialog__actions">
        <button ref={cancelRef} type="button" disabled={busy} onClick={onCancel}>
          Go back
        </button>
        <button
          type="button"
          className={destructive ? "danger-button" : "primary-button"}
          disabled={busy}
          onClick={onConfirm}
        >
          {busy ? "Submitting…" : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
