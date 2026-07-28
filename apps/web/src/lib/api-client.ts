import { z, type ZodType } from "zod";

import {
  aiResultSchema,
  askAIInputSchema,
  canvasEdgeSchema,
  canvasNodeSchema,
  canvasSchema,
  canvasSnapshotSchema,
  controlledDraftCancellationSchema,
  controlledDraftSchema,
  controlledDraftPreparedSchema,
  controlledDraftStartInputSchema,
  reversibleWriteRollbackApprovalSchema,
  reversibleWriteRollbackInputSchema,
  reversibleWriteRollbackResultSchema,
  reversibleWriteRollbackReviewSchema,
  createCanvasInputSchema,
  createEdgeInputSchema,
  createNodeInputSchema,
  documentMetadataSchema,
  documentSearchInputSchema,
  documentSearchResultSchema,
  documentTextSchema,
  documentUploadResultSchema,
  indexRequestSchema,
  problemDetailsSchema,
  runtimeModeSchema,
  authSessionSchema,
  passwordResetRequestSchema,
  userSchema,
  workspaceSchema,
  sourcePassageSchema,
  updateNodeInputSchema,
  viewportSchema,
  type AIResult,
  type AskAIInput,
  type Canvas,
  type CanvasEdge,
  type CanvasSnapshot,
  type ControlledDraft,
  type ControlledDraftPrepared,
  type ControlledDraftCancellation,
  type ControlledDraftStartInput,
  type CreateEdgeInput,
  type CreateNodeInput,
  type DocumentSearchInput,
  type UpdateNodeInput,
  type RuntimeMode,
  type ReversibleWriteRollbackApproval,
  type ReversibleWriteRollbackResult,
  type ReversibleWriteRollbackReview,
} from "./contracts";
import {
  activitySchema,
  apaRenderSchema,
  evidenceBundleSchema,
  graphRelationshipSchema,
  graphRetrievalSchema,
  retrievalTraceSummarySchema,
  universeViewportSchema,
  workflowExecutionSchema,
  type EvidenceBundle,
  type UniverseViewport,
  type WorkflowExecution,
} from "./universe-contracts";
import {
  agentActivationRequestSchema,
  agentEvaluationSchema,
  agentInvocationSchema,
  agentProposalSchema,
  agentRegistriesSchema,
  agentValidationSchema,
  boundedAgentSchema,
  communicationProfileSchema,
  communicationRevisionSchema,
  type AgentActivationRequest,
  type AgentInvocation,
  type AgentRegistries,
  type BoundedAgent,
  type CommunicationProfile,
  type CommunicationRevision,
} from "./agent-studio-contracts";
import {
  approvalAuthoritySchema,
  collaborationActivitySchema,
  collaborationContextSchema,
  commentRevisionSchema,
  commentSchema,
  commentThreadSchema,
  invitationSchema,
  membershipSchema,
  ownershipTransferSchema,
  resourceOwnershipSchema,
  shareSchema,
  sharedAgentSchema,
  sharedWorkflowSchema,
} from "./collaboration-contracts";

const DEFAULT_API_URL = "http://localhost:8000/api/v1";
const API_TIMEOUT_MS = 20_000;
const LONG_OPERATION_TIMEOUT_MS = 180_000;
const CSRF_COOKIE_NAME = process.env.NEXT_PUBLIC_CSRF_COOKIE_NAME ?? "mobius_session_csrf";

function csrfHeaders(method: string | undefined): Record<string, string> {
  if (!method || ["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase())) return {};
  const prefix = `${encodeURIComponent(CSRF_COOKIE_NAME)}=`;
  const token = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length);
  return token ? { "X-CSRF-Token": decodeURIComponent(token) } : {};
}

function getApiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL).replace(/\/$/, "");
}

export class APIError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;

  constructor(message: string, options: { status: number; code?: string; requestId?: string }) {
    super(message);
    this.name = "APIError";
    this.status = options.status;
    this.code = options.code ?? "api_error";
    this.requestId = options.requestId;
  }
}

async function parseError(response: Response): Promise<APIError> {
  const fallback = `Request failed with status ${response.status}`;

  try {
    const payload: unknown = await response.json();
    const parsed = problemDetailsSchema.safeParse(payload);
    if (!parsed.success) return new APIError(fallback, { status: response.status });

    const detail = parsed.data.detail;
    const nestedMessage =
      detail && !Array.isArray(detail) && typeof detail === "object" ? detail.message : undefined;
    const nestedCode =
      detail && !Array.isArray(detail) && typeof detail === "object" ? detail.code : undefined;
    const message =
      typeof detail === "string"
        ? detail
        : (nestedMessage ??
          parsed.data.title ??
          (response.status === 422 ? "The request was invalid." : fallback));

    return new APIError(message, {
      status: response.status,
      code: parsed.data.code ?? nestedCode,
      requestId: parsed.data.requestId ?? response.headers.get("x-request-id") ?? undefined,
    });
  } catch {
    return new APIError(fallback, { status: response.status });
  }
}

async function request<T>(
  path: string,
  schema: ZodType<T>,
  init: RequestInit = {},
  timeoutMs = API_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort("timeout"), timeoutMs);
  const abort = () => controller.abort(init.signal?.reason);
  init.signal?.addEventListener("abort", abort, { once: true });

  try {
    const hasFormDataBody = typeof FormData !== "undefined" && init.body instanceof FormData;
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
      signal: controller.signal,
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...(init.body && !hasFormDataBody ? { "Content-Type": "application/json" } : {}),
        ...csrfHeaders(init.method),
        ...init.headers,
      },
    });

    if (!response.ok) throw await parseError(response);

    const payload: unknown = await response.json();
    const parsed = schema.safeParse(payload);
    if (!parsed.success) {
      throw new APIError("The server returned an unexpected response.", {
        status: 502,
        code: "invalid_response",
        requestId: response.headers.get("x-request-id") ?? undefined,
      });
    }
    return parsed.data;
  } catch (error) {
    if (error instanceof APIError) throw error;
    if (controller.signal.aborted) {
      throw new APIError("The request timed out or was cancelled.", {
        status: 408,
        code: "request_aborted",
      });
    }
    throw new APIError("Could not reach the SolarPlexus Mobius server.", {
      status: 0,
      code: "network_error",
    });
  } finally {
    window.clearTimeout(timeout);
    init.signal?.removeEventListener("abort", abort);
  }
}

async function requestWithoutBody(path: string, init: RequestInit): Promise<void> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort("timeout"), API_TIMEOUT_MS);

  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
      signal: controller.signal,
      credentials: "include",
      headers: { Accept: "application/json", ...csrfHeaders(init.method), ...init.headers },
    });
    if (!response.ok) throw await parseError(response);
  } catch (error) {
    if (error instanceof APIError) throw error;
    throw new APIError("Could not reach the SolarPlexus Mobius server.", {
      status: 0,
      code: "network_error",
    });
  } finally {
    window.clearTimeout(timeout);
  }
}

async function requestZip(path: string): Promise<Blob> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort("timeout"), LONG_OPERATION_TIMEOUT_MS);
  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      method: "POST",
      signal: controller.signal,
      credentials: "include",
      headers: { Accept: "application/zip", ...csrfHeaders("POST") },
    });
    if (!response.ok) throw await parseError(response);
    const contentType = response.headers.get("content-type")?.split(";").at(0)?.trim();
    if (!["application/zip", "application/octet-stream"].includes(contentType ?? "")) {
      throw new APIError("The evidence bundle response was not a safe ZIP file.", {
        status: 502,
        code: "unsafe_bundle_response",
      });
    }
    const declaredSize = Number(response.headers.get("content-length") ?? "0");
    if (Number.isFinite(declaredSize) && declaredSize > 100_000_000) {
      throw new APIError("The evidence bundle exceeds the download limit.", {
        status: 413,
        code: "bundle_too_large",
      });
    }
    const blob = await response.blob();
    if (blob.size > 100_000_000) {
      throw new APIError("The evidence bundle exceeds the download limit.", {
        status: 413,
        code: "bundle_too_large",
      });
    }
    return blob;
  } catch (error) {
    if (error instanceof APIError) throw error;
    throw new APIError("Could not download the evidence bundle.", {
      status: controller.signal.aborted ? 408 : 0,
      code: controller.signal.aborted ? "request_aborted" : "network_error",
    });
  } finally {
    window.clearTimeout(timeout);
  }
}

export const canvasApi = {
  getRuntimeMode(signal?: AbortSignal): Promise<RuntimeMode> {
    return request("/health/runtime", runtimeModeSchema, { signal });
  },
  listCanvases(workspaceId?: string, signal?: AbortSignal): Promise<Canvas[]> {
    const query = workspaceId ? `?workspaceId=${encodeURIComponent(workspaceId)}` : "";
    return request(`/canvases${query}`, z.array(canvasSchema), { signal });
  },

  createCanvas(name: string, workspaceId?: string): Promise<Canvas> {
    const input = createCanvasInputSchema.parse({ name, workspaceId });
    return request("/canvases", canvasSchema, { method: "POST", body: JSON.stringify(input) });
  },

  getSnapshot(canvasId: string, signal?: AbortSignal): Promise<CanvasSnapshot> {
    return request(`/canvases/${encodeURIComponent(canvasId)}/snapshot`, canvasSnapshotSchema, {
      signal,
    });
  },

  updateCanvas(
    canvasId: string,
    input: { revision: number; name?: string; viewport?: z.infer<typeof viewportSchema> },
  ): Promise<Canvas> {
    return request(`/canvases/${encodeURIComponent(canvasId)}`, canvasSchema, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  },

  createNode(canvasId: string, rawInput: CreateNodeInput) {
    const input = createNodeInputSchema.parse(rawInput);
    return request(`/canvases/${encodeURIComponent(canvasId)}/nodes`, canvasNodeSchema, {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  updateNode(canvasId: string, nodeId: string, rawInput: UpdateNodeInput) {
    const input = updateNodeInputSchema.parse(rawInput);
    return request(
      `/canvases/${encodeURIComponent(canvasId)}/nodes/${encodeURIComponent(nodeId)}`,
      canvasNodeSchema,
      { method: "PATCH", body: JSON.stringify(input) },
    );
  },

  duplicateNode(
    canvasId: string,
    nodeId: string,
    revision: number,
    position: { x: number; y: number },
  ) {
    return request(
      `/canvases/${encodeURIComponent(canvasId)}/nodes/${encodeURIComponent(nodeId)}/duplicate`,
      canvasNodeSchema,
      { method: "POST", body: JSON.stringify({ revision, position }) },
    );
  },

  deleteNode(canvasId: string, nodeId: string, revision: number): Promise<void> {
    return requestWithoutBody(
      `/canvases/${encodeURIComponent(canvasId)}/nodes/${encodeURIComponent(nodeId)}?revision=${revision}`,
      { method: "DELETE" },
    );
  },

  createEdge(canvasId: string, rawInput: CreateEdgeInput): Promise<CanvasEdge> {
    const input = createEdgeInputSchema.parse(rawInput);
    return request(`/canvases/${encodeURIComponent(canvasId)}/edges`, canvasEdgeSchema, {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  deleteEdge(canvasId: string, edgeId: string, revision: number): Promise<void> {
    return requestWithoutBody(
      `/canvases/${encodeURIComponent(canvasId)}/edges/${encodeURIComponent(edgeId)}?revision=${revision}`,
      { method: "DELETE" },
    );
  },

  askAI(canvasId: string, rawInput: AskAIInput): Promise<AIResult> {
    const input = askAIInputSchema.parse(rawInput);
    return request(
      `/canvases/${encodeURIComponent(canvasId)}/ai`,
      aiResultSchema,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
      LONG_OPERATION_TIMEOUT_MS,
    );
  },

  rerunAI(canvasId: string, requestId: string, context: "original" | "current") {
    return request(
      `/canvases/${encodeURIComponent(canvasId)}/ai/${encodeURIComponent(requestId)}/rerun-${context}`,
      aiResultSchema,
      { method: "POST" },
      LONG_OPERATION_TIMEOUT_MS,
    );
  },

  uploadDocument(canvasId: string, file: File, position: { x: number; y: number }) {
    const form = new FormData();
    form.set("file", file, file.name);
    form.set("x", String(position.x));
    form.set("y", String(position.y));
    return request(
      `/canvases/${encodeURIComponent(canvasId)}/documents`,
      documentUploadResultSchema,
      { method: "POST", body: form },
      LONG_OPERATION_TIMEOUT_MS,
    );
  },

  getDocument(documentId: string, signal?: AbortSignal) {
    return request(`/documents/${encodeURIComponent(documentId)}`, documentMetadataSchema, {
      signal,
    });
  },

  getDocumentText(documentId: string, signal?: AbortSignal) {
    return request(`/documents/${encodeURIComponent(documentId)}/text`, documentTextSchema, {
      signal,
    });
  },

  getSourcePassage(documentId: string, chunkId: string, signal?: AbortSignal) {
    return request(
      `/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}`,
      sourcePassageSchema,
      { signal },
    );
  },

  retryDocument(documentId: string) {
    return request(`/documents/${encodeURIComponent(documentId)}/retry`, documentMetadataSchema, {
      method: "POST",
    });
  },

  deleteDocument(documentId: string): Promise<void> {
    return requestWithoutBody(`/documents/${encodeURIComponent(documentId)}`, {
      method: "DELETE",
    });
  },

  searchDocuments(canvasId: string, rawInput: DocumentSearchInput) {
    const input = documentSearchInputSchema.parse(rawInput);
    return request(
      `/canvases/${encodeURIComponent(canvasId)}/documents/search`,
      documentSearchResultSchema,
      { method: "POST", body: JSON.stringify(input) },
    );
  },

  reindexDocument(workspaceId: string, canvasId: string, documentId: string) {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/documents/${encodeURIComponent(documentId)}/reindex`,
      indexRequestSchema,
      {
        method: "POST",
        body: JSON.stringify({ idempotencyKey: `reindex-${crypto.randomUUID()}` }),
      },
      LONG_OPERATION_TIMEOUT_MS,
    );
  },

  getIndexRequest(workspaceId: string, canvasId: string, requestId: string, signal?: AbortSignal) {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/index-requests/${encodeURIComponent(requestId)}`,
      indexRequestSchema,
      { signal },
    );
  },

  cancelIndexRequest(workspaceId: string, canvasId: string, requestId: string) {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/index-requests/${encodeURIComponent(requestId)}/cancel`,
      indexRequestSchema,
      { method: "POST" },
    );
  },
};

export const agentApi = {
  reviewReversibleWriteRollback(
    workspaceId: string,
    canvasId: string,
    effectId: string,
    signal?: AbortSignal,
  ): Promise<ReversibleWriteRollbackReview> {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/agent-executions/canvases/${encodeURIComponent(canvasId)}/reversible-effects/${encodeURIComponent(effectId)}/rollback-review`,
      reversibleWriteRollbackReviewSchema,
      { signal },
    );
  },

  issueReversibleWriteRollbackApproval(
    workspaceId: string,
    canvasId: string,
    effectId: string,
    idempotencyKey: string,
  ): Promise<ReversibleWriteRollbackApproval> {
    const input = reversibleWriteRollbackInputSchema.parse({ idempotencyKey });
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/agent-executions/canvases/${encodeURIComponent(canvasId)}/reversible-effects/${encodeURIComponent(effectId)}/rollback-approval`,
      reversibleWriteRollbackApprovalSchema,
      { method: "POST", body: JSON.stringify(input) },
    );
  },

  executeReversibleWriteRollback(
    workspaceId: string,
    canvasId: string,
    effectId: string,
    rollbackApprovalId: string,
    idempotencyKey: string,
  ): Promise<ReversibleWriteRollbackResult> {
    const input = reversibleWriteRollbackInputSchema.parse({ idempotencyKey });
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/agent-executions/canvases/${encodeURIComponent(canvasId)}/reversible-effects/${encodeURIComponent(effectId)}/rollback-approvals/${encodeURIComponent(rollbackApprovalId)}/execute`,
      reversibleWriteRollbackResultSchema,
      { method: "POST", body: JSON.stringify(input) },
    );
  },

  prepareGroundedDraft(
    workspaceId: string,
    rawInput: ControlledDraftStartInput,
  ): Promise<ControlledDraftPrepared> {
    const input = controlledDraftStartInputSchema.parse(rawInput);
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/agent-executions/drafts/prepare`,
      controlledDraftPreparedSchema,
      { method: "POST", body: JSON.stringify(input) },
    );
  },

  runGroundedDraft(workspaceId: string, executionId: string): Promise<ControlledDraft> {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/agent-executions/${encodeURIComponent(executionId)}/run`,
      controlledDraftSchema,
      { method: "POST" },
      LONG_OPERATION_TIMEOUT_MS,
    );
  },

  startGroundedDraft(
    workspaceId: string,
    rawInput: ControlledDraftStartInput,
  ): Promise<ControlledDraft> {
    const input = controlledDraftStartInputSchema.parse(rawInput);
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/agent-executions/drafts`,
      controlledDraftSchema,
      { method: "POST", body: JSON.stringify(input) },
      LONG_OPERATION_TIMEOUT_MS,
    );
  },

  cancelExecution(
    workspaceId: string,
    executionId: string,
    idempotencyKey: string,
  ): Promise<ControlledDraftCancellation> {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/agent-executions/${encodeURIComponent(executionId)}/cancel`,
      controlledDraftCancellationSchema,
      { method: "POST", body: JSON.stringify({ idempotencyKey }) },
    );
  },
};

export const workspaceApi = {
  list(signal?: AbortSignal) {
    return request("/workspaces", z.array(workspaceSchema), { signal });
  },
  create(name: string) {
    return request("/workspaces", workspaceSchema, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  },
};

function collaborationPath(workspaceId: string): string {
  return `/workspaces/${encodeURIComponent(workspaceId)}`;
}

function resourcePath(workspaceId: string, resourceKind: string, resourceId: string): string {
  return `${collaborationPath(workspaceId)}/resources/${encodeURIComponent(resourceKind)}/${encodeURIComponent(resourceId)}`;
}

export const collaborationApi = {
  context(workspaceId: string, signal?: AbortSignal) {
    return request(
      `${collaborationPath(workspaceId)}/collaboration-context`,
      collaborationContextSchema,
      { signal },
    );
  },
  memberships(workspaceId: string, signal?: AbortSignal) {
    return request(`${collaborationPath(workspaceId)}/memberships`, z.array(membershipSchema), {
      signal,
    });
  },
  membershipCommand(
    workspaceId: string,
    membershipId: string,
    operation: "suspend" | "restore" | "remove",
    idempotencyKey: string,
  ) {
    return request(
      `${collaborationPath(workspaceId)}/memberships/${encodeURIComponent(membershipId)}/${operation}`,
      membershipSchema,
      { method: "POST", body: JSON.stringify({ idempotencyKey }) },
    );
  },
  changeRole(workspaceId: string, membershipId: string, role: string, idempotencyKey: string) {
    return request(
      `${collaborationPath(workspaceId)}/memberships/${encodeURIComponent(membershipId)}/role`,
      membershipSchema,
      { method: "POST", body: JSON.stringify({ role, idempotencyKey }) },
    );
  },
  invitations(workspaceId: string, signal?: AbortSignal) {
    return request(`${collaborationPath(workspaceId)}/invitations`, z.array(invitationSchema), {
      signal,
    });
  },
  createInvitation(
    workspaceId: string,
    input: {
      recipientEmail: string;
      intendedRole: string;
      expiresInDays: number;
      idempotencyKey: string;
    },
  ) {
    return request(`${collaborationPath(workspaceId)}/invitations`, invitationSchema, {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  invitationCommand(
    workspaceId: string,
    invitationId: string,
    operation: "resend" | "revoke",
    idempotencyKey: string,
  ) {
    return request(
      `${collaborationPath(workspaceId)}/invitations/${encodeURIComponent(invitationId)}/${operation}`,
      invitationSchema,
      { method: "POST", body: JSON.stringify({ idempotencyKey }) },
    );
  },
  invitationDecision(
    invitationId: string,
    operation: "accept" | "decline",
    token: string,
    idempotencyKey: string,
  ) {
    if (operation === "accept") {
      return request(
        `/collaboration-invitations/${encodeURIComponent(invitationId)}/accept`,
        membershipSchema,
        {
          method: "POST",
          body: JSON.stringify({ token, idempotencyKey }),
        },
      );
    }
    return request(
      `/collaboration-invitations/${encodeURIComponent(invitationId)}/decline`,
      invitationSchema,
      {
        method: "POST",
        body: JSON.stringify({ token, idempotencyKey }),
      },
    );
  },
  approvalAuthorities(workspaceId: string, signal?: AbortSignal) {
    return request(
      `${collaborationPath(workspaceId)}/approval-authority`,
      z.array(approvalAuthoritySchema),
      { signal },
    );
  },
  assignApprovalAuthority(workspaceId: string, input: Record<string, unknown>) {
    return request(
      `${collaborationPath(workspaceId)}/approval-authority`,
      approvalAuthoritySchema,
      { method: "POST", body: JSON.stringify(input) },
    );
  },
  revokeApprovalAuthority(workspaceId: string, assignmentId: string, idempotencyKey: string) {
    return request(
      `${collaborationPath(workspaceId)}/approval-authority/${encodeURIComponent(assignmentId)}/revoke`,
      approvalAuthoritySchema,
      { method: "POST", body: JSON.stringify({ idempotencyKey }) },
    );
  },
  shares(workspaceId: string, signal?: AbortSignal) {
    return request(`${collaborationPath(workspaceId)}/shares`, z.array(shareSchema), { signal });
  },
  createShares(workspaceId: string, targets: unknown[], idempotencyKey: string) {
    return request(`${collaborationPath(workspaceId)}/shares`, z.array(shareSchema), {
      method: "POST",
      body: JSON.stringify({ targets, idempotencyKey }),
    });
  },
  revokeShares(workspaceId: string, shareIds: string[], idempotencyKey: string) {
    return request(`${collaborationPath(workspaceId)}/shares/revoke`, z.array(shareSchema), {
      method: "POST",
      body: JSON.stringify({ shareIds, idempotencyKey }),
    });
  },
  ownership(workspaceId: string, resourceKind: string, resourceId: string, signal?: AbortSignal) {
    return request(
      `${resourcePath(workspaceId, resourceKind, resourceId)}/ownership`,
      resourceOwnershipSchema,
      { signal },
    );
  },
  setVisibility(
    workspaceId: string,
    resourceKind: string,
    resourceId: string,
    visibilityPolicy: string,
    idempotencyKey: string,
  ) {
    return request(
      `${resourcePath(workspaceId, resourceKind, resourceId)}/visibility`,
      resourceOwnershipSchema,
      { method: "POST", body: JSON.stringify({ visibilityPolicy, idempotencyKey }) },
    );
  },
  ownershipTransfers(workspaceId: string, signal?: AbortSignal) {
    return request(
      `${collaborationPath(workspaceId)}/ownership-transfers`,
      z.array(ownershipTransferSchema),
      { signal },
    );
  },
  requestOwnershipTransfer(workspaceId: string, input: Record<string, unknown>) {
    return request(
      `${collaborationPath(workspaceId)}/ownership-transfers`,
      ownershipTransferSchema,
      { method: "POST", body: JSON.stringify(input) },
    );
  },
  ownershipTransferDecision(
    workspaceId: string,
    transferId: string,
    operation: "accept" | "reject" | "cancel",
    idempotencyKey: string,
  ) {
    return request(
      `${collaborationPath(workspaceId)}/ownership-transfers/${encodeURIComponent(transferId)}/${operation}`,
      ownershipTransferSchema,
      { method: "POST", body: JSON.stringify({ idempotencyKey }) },
    );
  },
  comments(workspaceId: string, resourceKind: string, resourceId: string, signal?: AbortSignal) {
    return request(
      `${resourcePath(workspaceId, resourceKind, resourceId)}/comments`,
      z.array(commentSchema),
      { signal },
    );
  },
  createComment(
    workspaceId: string,
    resourceKind: string,
    resourceId: string,
    content: string,
    parentCommentId: string | null,
    idempotencyKey: string,
  ) {
    return request(
      `${resourcePath(workspaceId, resourceKind, resourceId)}/comments`,
      commentSchema,
      { method: "POST", body: JSON.stringify({ content, parentCommentId, idempotencyKey }) },
    );
  },
  commentRevisions(
    workspaceId: string,
    resourceKind: string,
    resourceId: string,
    commentId: string,
    signal?: AbortSignal,
  ) {
    return request(
      `${collaborationPath(workspaceId)}/comments/${encodeURIComponent(commentId)}/revisions`,
      z.array(commentRevisionSchema),
      { signal },
    );
  },
  reviseComment(
    workspaceId: string,
    resourceKind: string,
    resourceId: string,
    commentId: string,
    expectedRevisionId: string,
    content: string,
    idempotencyKey: string,
  ) {
    return request(
      `${collaborationPath(workspaceId)}/comments/${encodeURIComponent(commentId)}/revisions`,
      commentRevisionSchema,
      {
        method: "POST",
        body: JSON.stringify({ expectedRevisionId, content, idempotencyKey }),
      },
    );
  },
  tombstoneComment(
    workspaceId: string,
    resourceKind: string,
    resourceId: string,
    commentId: string,
    tombstoneKind: "remove_by_author" | "hide_by_moderation",
    idempotencyKey: string,
  ) {
    return request(
      `${collaborationPath(workspaceId)}/comments/${encodeURIComponent(commentId)}/moderate`,
      commentSchema,
      {
        method: "POST",
        body: JSON.stringify({
          tombstoneKind,
          reasonCode: "user_requested",
          idempotencyKey,
        }),
      },
    );
  },
  setThreadState(
    workspaceId: string,
    resourceKind: string,
    resourceId: string,
    threadId: string,
    targetState: "resolved" | "reopened",
    idempotencyKey: string,
  ) {
    return request(
      `${collaborationPath(workspaceId)}/comment-threads/${encodeURIComponent(threadId)}/resolve`,
      commentThreadSchema,
      { method: "POST", body: JSON.stringify({ targetState, idempotencyKey }) },
    );
  },
  activity(workspaceId: string, signal?: AbortSignal) {
    return request(
      `${collaborationPath(workspaceId)}/collaboration-activity`,
      z.array(collaborationActivitySchema),
      { signal },
    );
  },
  workflows(workspaceId: string, canvasId: string, signal?: AbortSignal) {
    return request(
      `${collaborationPath(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/workflows`,
      z.array(sharedWorkflowSchema),
      { signal },
    );
  },
  startWorkflow(
    workspaceId: string,
    canvasId: string,
    input: Record<string, unknown>,
  ): Promise<WorkflowExecution> {
    return request(
      `${collaborationPath(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/workflows/executions`,
      workflowExecutionSchema,
      { method: "POST", body: JSON.stringify(input) },
      LONG_OPERATION_TIMEOUT_MS,
    );
  },
  agents(workspaceId: string, canvasId: string, signal?: AbortSignal) {
    return request(
      `${collaborationPath(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/agent-studio/agents`,
      z.array(sharedAgentSchema),
      { signal },
    );
  },
  invokeAgent(
    workspaceId: string,
    canvasId: string,
    agentId: string,
    input: Record<string, unknown>,
  ): Promise<AgentInvocation> {
    return request(
      `${collaborationPath(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/agent-studio/agents/${encodeURIComponent(agentId)}/invocations`,
      agentInvocationSchema,
      { method: "POST", body: JSON.stringify(input) },
      LONG_OPERATION_TIMEOUT_MS,
    );
  },
};

export const universeApi = {
  getViewport(
    canvasId: string,
    options: {
      minX?: number;
      minY?: number;
      maxX?: number;
      maxY?: number;
      limit?: number;
      cursor?: string;
      expectedCanvasRevision?: number;
      selectionIds?: readonly string[];
      signal?: AbortSignal;
    } = {},
  ): Promise<UniverseViewport> {
    const query = new URLSearchParams({
      minX: String(options.minX ?? -50_000),
      minY: String(options.minY ?? -50_000),
      maxX: String(options.maxX ?? 50_000),
      maxY: String(options.maxY ?? 50_000),
      limit: String(options.limit ?? 100),
    });
    if (options.cursor) query.set("cursor", options.cursor);
    if (options.expectedCanvasRevision !== undefined) {
      query.set("expectedCanvasRevision", String(options.expectedCanvasRevision));
    }
    options.selectionIds?.forEach((id) => query.append("selectionId", id));
    return request(
      `/canvases/${encodeURIComponent(canvasId)}/universe-viewport?${query.toString()}`,
      universeViewportSchema,
      { signal: options.signal },
    );
  },

  getRelationships(
    workspaceId: string,
    canvasId: string,
    entityId: string,
    options: {
      includeInactive?: boolean;
      limit?: number;
      offset?: number;
      signal?: AbortSignal;
    } = {},
  ) {
    const query = new URLSearchParams({
      includeInactive: String(options.includeInactive ?? true),
      limit: String(options.limit ?? 50),
      offset: String(options.offset ?? 0),
    });
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/knowledge-graph/entities/${encodeURIComponent(entityId)}/relationships?${query.toString()}`,
      z.array(graphRelationshipSchema).max(100),
      { signal: options.signal },
    );
  },

  getActivity(
    workspaceId: string,
    canvasId: string,
    options: { limit?: number; offset?: number; signal?: AbortSignal } = {},
  ) {
    const query = new URLSearchParams({
      limit: String(options.limit ?? 30),
      offset: String(options.offset ?? 0),
    });
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/activity?${query.toString()}`,
      z.array(activitySchema).max(100),
      { signal: options.signal },
    );
  },

  getRetrieval(workspaceId: string, canvasId: string, retrievalId: string, signal?: AbortSignal) {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/graph-retrievals/${encodeURIComponent(retrievalId)}`,
      graphRetrievalSchema,
      { signal },
    );
  },

  getRetrievalTrace(
    workspaceId: string,
    canvasId: string,
    retrievalId: string,
    signal?: AbortSignal,
  ) {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/graph-retrievals/${encodeURIComponent(retrievalId)}/trace`,
      retrievalTraceSummarySchema,
      { signal },
    );
  },

  renderApa(workspaceId: string, canvasId: string, retrievalId: string) {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/graph-retrievals/${encodeURIComponent(retrievalId)}/citations/render`,
      apaRenderSchema,
      { method: "POST" },
    );
  },

  getWorkflow(
    workspaceId: string,
    canvasId: string,
    executionId: string,
    signal?: AbortSignal,
  ): Promise<WorkflowExecution> {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/workflows/executions/${encodeURIComponent(executionId)}`,
      workflowExecutionSchema,
      { signal },
    );
  },

  decideApproval(
    workspaceId: string,
    canvasId: string,
    executionId: string,
    stepExecutionId: string,
    decision: "approved" | "denied",
  ): Promise<WorkflowExecution> {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/workflows/executions/${encodeURIComponent(executionId)}/steps/${encodeURIComponent(stepExecutionId)}/approval`,
      workflowExecutionSchema,
      { method: "POST", body: JSON.stringify({ decision }) },
    );
  },

  cancelWorkflow(
    workspaceId: string,
    canvasId: string,
    executionId: string,
  ): Promise<WorkflowExecution> {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/workflows/executions/${encodeURIComponent(executionId)}/cancel`,
      workflowExecutionSchema,
      { method: "POST" },
    );
  },

  generateBundle(
    workspaceId: string,
    canvasId: string,
    retrievalId: string,
  ): Promise<EvidenceBundle> {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/graph-retrievals/${encodeURIComponent(retrievalId)}/evidence-bundle`,
      evidenceBundleSchema,
      { method: "POST", body: JSON.stringify({ includeAuthorizedSources: false }) },
    );
  },

  getBundle(workspaceId: string, canvasId: string, bundleId: string, signal?: AbortSignal) {
    return request(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/evidence-bundles/${encodeURIComponent(bundleId)}`,
      evidenceBundleSchema,
      { signal },
    );
  },

  downloadBundle(workspaceId: string, canvasId: string, bundleId: string) {
    return requestZip(
      `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/evidence-bundles/${encodeURIComponent(bundleId)}/download`,
    );
  },
};

export const accountApi = {
  signUp(input: { email: string; password: string; displayName: string }) {
    return request("/auth/signup", authSessionSchema, {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  signIn(input: { email: string; password: string }) {
    return request("/auth/signin", authSessionSchema, {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  me(signal?: AbortSignal) {
    return request("/auth/me", userSchema, { signal });
  },
  signOut() {
    return requestWithoutBody("/auth/signout", { method: "POST" });
  },
  update(input: { displayName: string }) {
    return request("/account", userSchema, { method: "PATCH", body: JSON.stringify(input) });
  },
  requestReset(email: string) {
    return request("/auth/password-reset/request", passwordResetRequestSchema, {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  },
  confirmReset(token: string, password: string) {
    return requestWithoutBody("/auth/password-reset/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, password }),
    });
  },
  requestExport() {
    return request(
      "/account/export",
      z.object({ id: z.string().uuid(), status: z.string(), createdAt: z.string() }),
      { method: "POST" },
    );
  },
  delete(password: string) {
    return requestWithoutBody("/account", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password, confirmation: "DELETE MY ACCOUNT" }),
    });
  },
};

function agentStudioPath(workspaceId: string, canvasId: string): string {
  return `/workspaces/${encodeURIComponent(workspaceId)}/canvases/${encodeURIComponent(canvasId)}/agent-studio`;
}

export const agentStudioApi = {
  registries(
    workspaceId: string,
    canvasId: string,
    signal?: AbortSignal,
  ): Promise<AgentRegistries> {
    return request(`${agentStudioPath(workspaceId, canvasId)}/registries`, agentRegistriesSchema, {
      signal,
    });
  },

  list(
    workspaceId: string,
    canvasId: string,
    lifecycle?: string,
    signal?: AbortSignal,
  ): Promise<BoundedAgent[]> {
    const query = lifecycle ? `?lifecycle=${encodeURIComponent(lifecycle)}` : "";
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/agents${query}`,
      z.array(boundedAgentSchema).max(100),
      { signal },
    );
  },

  create(workspaceId: string, canvasId: string, input: unknown): Promise<BoundedAgent> {
    return request(`${agentStudioPath(workspaceId, canvasId)}/agents`, boundedAgentSchema, {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  createVersion(
    workspaceId: string,
    canvasId: string,
    agentId: string,
    input: unknown,
  ): Promise<BoundedAgent> {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/agents/${encodeURIComponent(agentId)}/versions`,
      boundedAgentSchema,
      { method: "POST", body: JSON.stringify(input) },
    );
  },

  validate(workspaceId: string, canvasId: string, versionId: string) {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/versions/${encodeURIComponent(versionId)}/validate`,
      agentValidationSchema,
      { method: "POST" },
    );
  },

  requestActivation(
    workspaceId: string,
    canvasId: string,
    versionId: string,
    idempotencyKey: string,
  ): Promise<AgentActivationRequest> {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/versions/${encodeURIComponent(versionId)}/activation-requests`,
      agentActivationRequestSchema,
      { method: "POST", body: JSON.stringify({ idempotencyKey }) },
    );
  },

  decideActivation(
    workspaceId: string,
    canvasId: string,
    requestId: string,
    decision: "approved" | "denied",
  ): Promise<AgentActivationRequest> {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/activation-requests/${encodeURIComponent(requestId)}/decision`,
      agentActivationRequestSchema,
      { method: "POST", body: JSON.stringify({ decision }) },
    );
  },

  invoke(
    workspaceId: string,
    canvasId: string,
    agentId: string,
    input: unknown,
  ): Promise<AgentInvocation> {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/agents/${encodeURIComponent(agentId)}/invocations`,
      agentInvocationSchema,
      { method: "POST", body: JSON.stringify(input) },
      LONG_OPERATION_TIMEOUT_MS,
    );
  },

  evaluate(workspaceId: string, canvasId: string, invocationId: string, input: unknown) {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/invocations/${encodeURIComponent(invocationId)}/evaluations`,
      agentEvaluationSchema,
      { method: "POST", body: JSON.stringify(input) },
    );
  },

  createProposal(workspaceId: string, canvasId: string, input: unknown) {
    return request(`${agentStudioPath(workspaceId, canvasId)}/proposals`, agentProposalSchema, {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  decideProposal(
    workspaceId: string,
    canvasId: string,
    proposalId: string,
    decision: "accepted" | "rejected",
  ) {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/proposals/${encodeURIComponent(proposalId)}/decision`,
      agentProposalSchema,
      { method: "POST", body: JSON.stringify({ decision }) },
    );
  },

  listProfiles(
    workspaceId: string,
    canvasId: string,
    signal?: AbortSignal,
  ): Promise<CommunicationProfile[]> {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/communication-profiles`,
      z.array(communicationProfileSchema).max(100),
      { signal },
    );
  },

  createProfile(
    workspaceId: string,
    canvasId: string,
    input: unknown,
  ): Promise<CommunicationProfile> {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/communication-profiles`,
      communicationProfileSchema,
      { method: "POST", body: JSON.stringify(input) },
    );
  },

  createProfileVersion(
    workspaceId: string,
    canvasId: string,
    profileId: string,
    input: unknown,
  ): Promise<CommunicationProfile> {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/communication-profiles/${encodeURIComponent(profileId)}/versions`,
      communicationProfileSchema,
      { method: "POST", body: JSON.stringify(input) },
    );
  },

  proposeRevision(
    workspaceId: string,
    canvasId: string,
    input: unknown,
  ): Promise<CommunicationRevision> {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/communication-revisions`,
      communicationRevisionSchema,
      { method: "POST", body: JSON.stringify(input) },
    );
  },

  decideRevision(
    workspaceId: string,
    canvasId: string,
    revisionId: string,
    decision: "accepted" | "rejected",
  ): Promise<CommunicationRevision> {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/communication-revisions/${encodeURIComponent(revisionId)}/decision`,
      communicationRevisionSchema,
      { method: "POST", body: JSON.stringify({ decision }) },
    );
  },

  lifecycle(
    workspaceId: string,
    canvasId: string,
    agentId: string,
    operation: "suspend" | "restore" | "retire",
  ): Promise<BoundedAgent> {
    return request(
      `${agentStudioPath(workspaceId, canvasId)}/agents/${encodeURIComponent(agentId)}/lifecycle`,
      boundedAgentSchema,
      {
        method: "POST",
        body: JSON.stringify({ operation, reasonCode: `human_${operation}` }),
      },
    );
  },
};

export function getTraceUrl(traceId: string): string {
  return `${getApiBaseUrl()}/traces/${encodeURIComponent(traceId)}`;
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof APIError || error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}
