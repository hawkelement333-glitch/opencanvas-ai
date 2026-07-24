import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, type Mock } from "vitest";

import { ReversibleEffectRollback } from "./reversible-effect-rollback";
import { APIError } from "@/lib/api-client";
import type {
  ReversibleWriteRollbackApproval,
  ReversibleWriteRollbackResult,
  ReversibleWriteRollbackReview,
} from "@/lib/contracts";

const effectId = "10000000-0000-4000-8000-000000000001";
const noteId = "20000000-0000-4000-8000-000000000001";
const approvalId = "30000000-0000-4000-8000-000000000001";

const createReview: ReversibleWriteRollbackReview = {
  effectId,
  forwardAction: "note.create",
  noteId,
  effectRevision: 0,
  currentRevision: 0,
  rollbackAction: "note.create.rollback",
  rollbackTargetKind: "authoritative_absence",
  requiredCapability: "canvas.note.create.rollback",
  eligible: true,
  approvalRequired: true,
  denialReason: null,
  conflict: false,
};

const updateReview: ReversibleWriteRollbackReview = {
  ...createReview,
  forwardAction: "note.update",
  effectRevision: 2,
  currentRevision: 2,
  rollbackAction: "note.update.rollback",
  rollbackTargetKind: "exact_prior_state",
  requiredCapability: "canvas.note.update.rollback",
};

function approval(review = createReview): ReversibleWriteRollbackApproval {
  return {
    rollbackApprovalId: approvalId,
    effectId,
    noteId,
    forwardAction: review.forwardAction!,
    rollbackAction: review.rollbackAction!,
    expectedCurrentRevision: review.currentRevision!,
    rollbackTargetKind: review.rollbackTargetKind!,
    expiresAt: "2026-07-24T19:15:00Z",
    duplicate: false,
  };
}

function result(review = createReview, duplicate = false): ReversibleWriteRollbackResult {
  return {
    rollbackResultId: "40000000-0000-4000-8000-000000000001",
    rollbackApprovalId: approvalId,
    effectId,
    noteId,
    rollbackAction: review.rollbackAction!,
    rollbackTargetKind: review.rollbackTargetKind!,
    resultingRevision: review.forwardAction === "note.create" ? null : 3,
    createdAt: "2026-07-24T19:01:00Z",
    duplicate,
  };
}

function setup(
  review: ReversibleWriteRollbackReview = createReview,
  overrides: {
    requestApproval?: Mock<(idempotencyKey: string) => Promise<ReversibleWriteRollbackApproval>>;
    executeRollback?: Mock<
      (rollbackApprovalId: string, idempotencyKey: string) => Promise<ReversibleWriteRollbackResult>
    >;
    onComplete?: Mock<(result: ReversibleWriteRollbackResult) => Promise<void> | void>;
  } = {},
) {
  const loadReview = vi.fn().mockResolvedValue(review);
  const requestApproval = overrides.requestApproval ?? vi.fn().mockResolvedValue(approval(review));
  const executeRollback = overrides.executeRollback ?? vi.fn().mockResolvedValue(result(review));
  const onComplete = overrides.onComplete ?? vi.fn();
  render(
    <ReversibleEffectRollback
      effectId={effectId}
      loadReview={loadReview}
      requestApproval={requestApproval}
      executeRollback={executeRollback}
      onComplete={onComplete}
    />,
  );
  return { loadReview, requestApproval, executeRollback, onComplete };
}

async function confirmAndApprove(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /Review note/i }));
  const dialog = screen.getByRole("alertdialog");
  expect(dialog).toHaveTextContent(/Remove the unchanged note|Restore the note title/i);
  await user.click(screen.getByRole("button", { name: "Confirm and request approval" }));
  expect(await screen.findByText("Approval issued")).toBeInTheDocument();
}

describe("ReversibleEffectRollback", () => {
  it.each([
    [createReview, "Reverse created note", "Created note removed."],
    [updateReview, "Restore previous note", "Previous note state restored."],
  ])("reviews, confirms, approves, and executes %s", async (review, label, completeCopy) => {
    const user = userEvent.setup();
    const callbacks = setup(review);

    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(callbacks.requestApproval).not.toHaveBeenCalled();
    await confirmAndApprove(user);
    expect(callbacks.requestApproval).toHaveBeenCalledWith(expect.stringMatching(/^rollback_/));
    await user.click(screen.getByRole("button", { name: "Execute rollback" }));

    expect(await screen.findByText(completeCopy)).toBeInTheDocument();
    expect(callbacks.executeRollback).toHaveBeenCalledWith(
      approvalId,
      expect.stringMatching(/^rollback_/),
    );
    expect(callbacks.onComplete).toHaveBeenCalledWith(result(review));
  });

  it("does not expose a rollback action for an ineligible review", async () => {
    setup({
      ...createReview,
      eligible: false,
      approvalRequired: false,
      denialReason: "revision_conflict",
      conflict: true,
    });

    expect(await screen.findByText(/note changed after this effect/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Review note/i })).not.toBeInTheDocument();
  });

  it("requires explicit confirmation and prevents duplicate approval requests", async () => {
    const user = userEvent.setup();
    let resolveApproval!: (value: ReversibleWriteRollbackApproval) => void;
    const requestApproval = vi.fn(
      () =>
        new Promise<ReversibleWriteRollbackApproval>((resolve) => {
          resolveApproval = resolve;
        }),
    );
    setup(createReview, { requestApproval });

    await user.click(await screen.findByRole("button", { name: /Review note removal/i }));
    expect(requestApproval).not.toHaveBeenCalled();
    const confirm = screen.getByRole("button", { name: "Confirm and request approval" });
    await user.click(confirm);
    expect(await screen.findByText(/Requesting rollback approval/i)).toBeInTheDocument();
    expect(requestApproval).toHaveBeenCalledTimes(1);
    resolveApproval(approval());
    expect(await screen.findByText("Approval issued")).toBeInTheDocument();
  });

  it("prevents duplicate execution while the request is pending", async () => {
    const user = userEvent.setup();
    let resolveExecution!: (value: ReversibleWriteRollbackResult) => void;
    const executeRollback = vi.fn(
      () =>
        new Promise<ReversibleWriteRollbackResult>((resolve) => {
          resolveExecution = resolve;
        }),
    );
    setup(createReview, { executeRollback });
    await confirmAndApprove(user);
    await user.click(screen.getByRole("button", { name: "Execute rollback" }));
    expect(await screen.findByText(/Applying verified rollback/i)).toBeInTheDocument();
    expect(executeRollback).toHaveBeenCalledTimes(1);
    resolveExecution(result());
    expect(await screen.findByTestId("rollback-complete")).toBeInTheDocument();
  });

  it("renders an exact duplicate as already complete", async () => {
    const user = userEvent.setup();
    setup(createReview, { executeRollback: vi.fn().mockResolvedValue(result(createReview, true)) });
    await confirmAndApprove(user);
    await user.click(screen.getByRole("button", { name: "Execute rollback" }));
    expect(await screen.findByText("Rollback was already complete.")).toBeInTheDocument();
  });

  it.each([
    ["approval_expired", "The rollback approval expired"],
    ["revision_conflict", "The note or rollback authority changed"],
    ["grant_revoked", "Rollback permission is no longer available"],
    ["csrf_invalid", "Your secure session could not authorize rollback"],
    ["database exploded SELECT secret", "Rollback could not be completed"],
  ])("renders safe closed error copy for %s", async (code, expected) => {
    const user = userEvent.setup();
    setup(createReview, {
      requestApproval: vi
        .fn()
        .mockRejectedValue(new APIError("private database stack", { status: 409, code })),
    });
    await user.click(await screen.findByRole("button", { name: /Review note removal/i }));
    await user.click(screen.getByRole("button", { name: "Confirm and request approval" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
    expect(screen.queryByText(/private database stack|SELECT secret/i)).not.toBeInTheDocument();
  });

  it("loads review again after a safe failure", async () => {
    const user = userEvent.setup();
    const { loadReview } = setup(createReview, {
      requestApproval: vi
        .fn()
        .mockRejectedValue(new APIError("denied", { status: 403, code: "scope_mismatch" })),
    });
    await user.click(await screen.findByRole("button", { name: /Review note removal/i }));
    await user.click(screen.getByRole("button", { name: "Confirm and request approval" }));
    await user.click(await screen.findByRole("button", { name: "Refresh review" }));
    await waitFor(() => expect(loadReview).toHaveBeenCalledTimes(2));
  });
});
