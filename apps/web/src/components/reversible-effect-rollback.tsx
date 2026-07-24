"use client";

import { CheckCircle2, CircleAlert, History, LoaderCircle, RotateCcw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { APIError } from "@/lib/api-client";
import type {
  ReversibleWriteRollbackApproval,
  ReversibleWriteRollbackResult,
  ReversibleWriteRollbackReview,
} from "@/lib/contracts";

interface ReversibleEffectRollbackProps {
  effectId: string;
  loadReview: (signal?: AbortSignal) => Promise<ReversibleWriteRollbackReview>;
  requestApproval: (idempotencyKey: string) => Promise<ReversibleWriteRollbackApproval>;
  executeRollback: (
    rollbackApprovalId: string,
    idempotencyKey: string,
  ) => Promise<ReversibleWriteRollbackResult>;
  onComplete: (result: ReversibleWriteRollbackResult) => Promise<void> | void;
}

type RollbackState =
  | { type: "loading" }
  | { type: "ineligible"; review: ReversibleWriteRollbackReview }
  | { type: "eligible"; review: ReversibleWriteRollbackReview; confirming: boolean }
  | { type: "requesting"; review: ReversibleWriteRollbackReview }
  | {
      type: "approved";
      review: ReversibleWriteRollbackReview;
      approval: ReversibleWriteRollbackApproval;
    }
  | {
      type: "executing";
      review: ReversibleWriteRollbackReview;
      approval: ReversibleWriteRollbackApproval;
    }
  | { type: "complete"; result: ReversibleWriteRollbackResult }
  | { type: "failed"; message: string };

function requestKey(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2, 18);
  return `${prefix}_${random.replaceAll("-", "_")}`;
}

function actionCopy(review: ReversibleWriteRollbackReview): {
  title: string;
  summary: string;
  button: string;
} {
  if (review.rollbackAction === "note.create.rollback") {
    return {
      title: "Reverse created note",
      summary: "Remove the unchanged note created by this completed effect.",
      button: "Review note removal",
    };
  }
  return {
    title: "Restore previous note",
    summary: "Restore the note title and text captured before this completed effect.",
    button: "Review note restoration",
  };
}

const conflictCodes = new Set([
  "revision_conflict",
  "state_conflict",
  "note_missing",
  "rollback_evidence_invalid",
  "rollback_evidence_missing",
  "idempotency_conflict",
]);
const authorityCodes = new Set([
  "capability_missing",
  "grant_expired",
  "grant_revoked",
  "grant_scope_mismatch",
  "scope_mismatch",
]);

function safeFailure(error: unknown): string {
  if (!(error instanceof APIError)) {
    return "Rollback could not be completed. Refresh the review and try again.";
  }
  if (error.code === "approval_expired") {
    return "The rollback approval expired. Refresh the review to request a new approval.";
  }
  if (error.code === "already_rolled_back") {
    return "This effect has already been rolled back.";
  }
  if (conflictCodes.has(error.code)) {
    return "The note or rollback authority changed. Refresh before trying again.";
  }
  if (authorityCodes.has(error.code) || error.status === 403) {
    return "Rollback permission is no longer available for this effect.";
  }
  if (error.status === 401 || error.code.includes("csrf")) {
    return "Your secure session could not authorize rollback. Sign in again and retry.";
  }
  return "Rollback could not be completed. Refresh the review and try again.";
}

function denialCopy(review: ReversibleWriteRollbackReview): string {
  if (review.denialReason === "already_rolled_back") return "This effect was already rolled back.";
  if (review.conflict || conflictCodes.has(review.denialReason ?? "")) {
    return "The note changed after this effect, so rollback is no longer safe.";
  }
  if (authorityCodes.has(review.denialReason ?? "")) {
    return "Rollback permission is unavailable or has expired.";
  }
  return "This completed effect is not eligible for rollback.";
}

export function ReversibleEffectRollback({
  effectId,
  loadReview,
  requestApproval,
  executeRollback,
  onComplete,
}: ReversibleEffectRollbackProps) {
  const [state, setState] = useState<RollbackState>({ type: "loading" });
  const approvalKey = useRef(requestKey("rollback_approval"));
  const executionKey = useRef(requestKey("rollback_execute"));
  const confirmationButtonRef = useRef<HTMLButtonElement>(null);
  const pending = state.type === "requesting" || state.type === "executing";

  const refresh = async (signal?: AbortSignal) => {
    setState({ type: "loading" });
    try {
      const review = await loadReview(signal);
      setState(
        review.eligible
          ? { type: "eligible", review, confirming: false }
          : { type: "ineligible", review },
      );
    } catch (error) {
      if (signal?.aborted) return;
      setState({ type: "failed", message: safeFailure(error) });
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void loadReview(controller.signal)
      .then((loaded) => {
        if (controller.signal.aborted) return;
        setState(
          loaded.eligible
            ? { type: "eligible", review: loaded, confirming: false }
            : { type: "ineligible", review: loaded },
        );
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setState({ type: "failed", message: safeFailure(error) });
        }
      });
    return () => controller.abort();
  }, [effectId, loadReview]);

  useEffect(() => {
    if (state.type === "eligible" && state.confirming) {
      confirmationButtonRef.current?.focus();
    }
  }, [state]);

  const approve = async () => {
    if (state.type !== "eligible" || pending) return;
    const review = state.review;
    setState({ type: "requesting", review });
    try {
      const approval = await requestApproval(approvalKey.current);
      setState({ type: "approved", review, approval });
    } catch (error) {
      setState({ type: "failed", message: safeFailure(error) });
    }
  };

  const execute = async () => {
    if (state.type !== "approved" || pending) return;
    const { review, approval } = state;
    setState({ type: "executing", review, approval });
    try {
      const result = await executeRollback(approval.rollbackApprovalId, executionKey.current);
      await onComplete(result);
      setState({ type: "complete", result });
    } catch (error) {
      setState({ type: "failed", message: safeFailure(error) });
    }
  };

  const review =
    state.type === "eligible" ||
    state.type === "ineligible" ||
    state.type === "requesting" ||
    state.type === "approved" ||
    state.type === "executing"
      ? state.review
      : null;
  const copy = review ? actionCopy(review) : null;

  return (
    <aside className="rollback-control" aria-labelledby="rollback-control-title">
      <header>
        <span aria-hidden="true">
          <History size={17} />
        </span>
        <div>
          <strong id="rollback-control-title">Reversible effect</strong>
          <small>Server-verified rollback</small>
        </div>
      </header>

      <div className="rollback-control__state" aria-live="polite" aria-atomic="true">
        {state.type === "loading" && (
          <p className="assistant-state--loading" role="status">
            <LoaderCircle className="spin" size={14} aria-hidden="true" /> Checking rollback
            eligibility…
          </p>
        )}
        {state.type === "ineligible" && (
          <p className="assistant-state--warning">
            <CircleAlert size={14} aria-hidden="true" /> {denialCopy(state.review)}
          </p>
        )}
        {state.type === "eligible" && copy && (
          <>
            <strong>{copy.title}</strong>
            <p>{copy.summary}</p>
            <button
              type="button"
              className="rollback-control__action"
              onClick={() => setState({ ...state, confirming: true })}
              disabled={pending}
            >
              <RotateCcw size={14} aria-hidden="true" /> {copy.button}
            </button>
          </>
        )}
        {state.type === "requesting" && (
          <p className="assistant-state--loading" role="status">
            <LoaderCircle className="spin" size={14} aria-hidden="true" /> Requesting rollback
            approval…
          </p>
        )}
        {state.type === "approved" && copy && (
          <>
            <strong>Approval issued</strong>
            <p>{copy.summary}</p>
            <button
              type="button"
              className="rollback-control__action"
              onClick={() => void execute()}
            >
              <RotateCcw size={14} aria-hidden="true" /> Execute rollback
            </button>
          </>
        )}
        {state.type === "executing" && (
          <p className="assistant-state--loading" role="status">
            <LoaderCircle className="spin" size={14} aria-hidden="true" /> Applying verified
            rollback…
          </p>
        )}
        {state.type === "complete" && (
          <p className="assistant-state--success" data-testid="rollback-complete">
            <CheckCircle2 size={14} aria-hidden="true" />{" "}
            {state.result.duplicate
              ? "Rollback was already complete."
              : state.result.rollbackAction === "note.create.rollback"
                ? "Created note removed."
                : "Previous note state restored."}
          </p>
        )}
        {state.type === "failed" && (
          <>
            <p className="assistant-state--error" role="alert">
              <CircleAlert size={14} aria-hidden="true" /> {state.message}
            </p>
            <button
              type="button"
              className="rollback-control__secondary"
              onClick={() => void refresh()}
            >
              Refresh review
            </button>
          </>
        )}
      </div>

      {state.type === "eligible" && state.confirming && copy && (
        <div
          className="rollback-confirmation"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="rollback-confirmation-title"
          aria-describedby="rollback-confirmation-summary"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setState({ ...state, confirming: false });
            }
          }}
        >
          <button
            type="button"
            className="rollback-confirmation__close"
            aria-label="Cancel rollback confirmation"
            onClick={() => setState({ ...state, confirming: false })}
          >
            <X size={15} aria-hidden="true" />
          </button>
          <strong id="rollback-confirmation-title">{copy.title}?</strong>
          <p id="rollback-confirmation-summary">{copy.summary}</p>
          <div>
            <button
              ref={confirmationButtonRef}
              type="button"
              className="rollback-control__secondary"
              onClick={() => setState({ ...state, confirming: false })}
            >
              Keep current note
            </button>
            <button
              type="button"
              className="rollback-control__action"
              onClick={() => void approve()}
            >
              Confirm and request approval
            </button>
          </div>
        </div>
      )}
    </aside>
  );
}
