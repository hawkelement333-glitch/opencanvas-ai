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
  createCanvasInputSchema,
  createEdgeInputSchema,
  createNodeInputSchema,
  documentMetadataSchema,
  documentSearchInputSchema,
  documentSearchResultSchema,
  documentTextSchema,
  documentUploadResultSchema,
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
} from "./contracts";

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
};

export const agentApi = {
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

export function getTraceUrl(traceId: string): string {
  return `${getApiBaseUrl()}/traces/${encodeURIComponent(traceId)}`;
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof APIError || error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}
