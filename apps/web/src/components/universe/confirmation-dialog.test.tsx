import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmationDialog } from "./confirmation-dialog";

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  });
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  });
});

describe("governed action confirmation", () => {
  it("requires a deliberate confirmation and submits only one user activation", () => {
    const confirm = vi.fn();
    const cancel = vi.fn();
    render(
      <ConfirmationDialog
        title="Approve exact step?"
        description="The server will revalidate authority."
        confirmLabel="Approve once"
        busy={false}
        onCancel={cancel}
        onConfirm={confirm}
      />,
    );

    expect(screen.getByRole("dialog")).toHaveAttribute("open");
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Approve once" }));
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("disables approval and denial controls while a submission is pending", () => {
    render(
      <ConfirmationDialog
        title="Deny exact step?"
        description="Changed approval context fails closed."
        confirmLabel="Deny once"
        destructive
        busy
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Submitting…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Go back" })).toBeDisabled();
  });

  it("supports Escape cancellation and keeps it disabled during submission", () => {
    const cancel = vi.fn();
    const { rerender } = render(
      <ConfirmationDialog
        title="Cancel workflow?"
        description="History remains."
        confirmLabel="Request cancellation"
        busy={false}
        onCancel={cancel}
        onConfirm={vi.fn()}
      />,
    );
    const dialog = screen.getByRole("dialog");
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    expect(cancel).toHaveBeenCalledTimes(1);

    rerender(
      <ConfirmationDialog
        title="Cancel workflow?"
        description="History remains."
        confirmLabel="Request cancellation"
        busy
        onCancel={cancel}
        onConfirm={vi.fn()}
      />,
    );
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    expect(cancel).toHaveBeenCalledTimes(1);
  });
});
