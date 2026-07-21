"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  SelectionMode,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type EdgeChange,
  type NodeChange,
  useReactFlow,
} from "@xyflow/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Check,
  CircleAlert,
  Cloud,
  CloudOff,
  FolderOpen,
  ExternalLink,
  LoaderCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Save,
  Sparkles,
  StickyNote,
  Upload,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
} from "react";

import { AssistantPanel } from "@/components/assistant-panel";
import { CanvasNodeActionsProvider, CanvasNodeCard } from "@/components/canvas/canvas-node";
import { DocumentNodeCard } from "@/components/canvas/document-node";
import { DocumentPreviewPanel } from "@/components/document-preview-panel";
import { canvasApi, getErrorMessage, getTraceUrl, workspaceApi } from "@/lib/api-client";
import { AutosaveQueue, type SaveState } from "@/lib/autosave-queue";
import {
  buildAIRequest,
  createNodeDraft,
  type Canvas,
  type CanvasNode,
  type Citation,
  type DocumentFileType,
  type DocumentMetadata,
  type RuntimeMode,
  type Workspace,
} from "@/lib/contracts";
import {
  removeDocumentCitations,
  removeResponseCitationEdges,
  selectedCanvasNodes,
  toFlowEdge,
  toFlowNode,
  upsertFlowEdges,
  type CanvasFlowEdge,
  type CanvasFlowNode,
  type NodeHandlers,
} from "@/lib/flow";

const LAST_CANVAS_KEY = "opencanvas:last-canvas";
const nodeTypes = { canvasCard: CanvasNodeCard, documentCard: DocumentNodeCard };
const SUPPORTED_DOCUMENT_EXTENSIONS = new Set(["pdf", "txt", "md", "markdown", "docx"]);
const CLIENT_DOCUMENT_SIZE_LIMIT = 25 * 1_024 * 1_024;

function isEditableTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

function now(): string {
  return new Date().toISOString();
}

function temporaryId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2);
  return `temp-${prefix}-${random}`;
}

function documentExtension(fileName: string): string {
  return fileName.split(".").pop()?.toLowerCase() ?? "";
}

function documentFileType(fileName: string): DocumentFileType | null {
  const extension = documentExtension(fileName);
  if (extension === "md" || extension === "markdown") return "markdown";
  if (extension === "pdf" || extension === "txt" || extension === "docx") return extension;
  return null;
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="route-state" role="status">
      <LoaderCircle className="spin" size={24} aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="route-state route-state--error" role="alert">
      <CircleAlert size={24} aria-hidden="true" />
      <h2>We couldn’t open your canvas</h2>
      <p>{message}</p>
      <button type="button" onClick={onRetry}>
        <RefreshCw size={15} aria-hidden="true" /> Try again
      </button>
      <a href="/sign-in">Sign in or restore your session</a>
    </div>
  );
}

export function DemoModeBanner({
  runtime,
  placement = "overlay",
}: {
  runtime: RuntimeMode;
  placement?: "overlay" | "sidebar";
}) {
  if (runtime.mode !== "deterministic_replay" || !runtime.demoTraceId) return null;
  return (
    <aside
      className={`demo-mode-banner demo-mode-banner--${placement}`}
      aria-label="Build Week deterministic demo mode"
    >
      <div>
        <strong>DEMO · deterministic replay</strong>
        <span>No account, production data, credentials, or external AI calls</span>
      </div>
      <ul aria-label="Evidence classifications shown in this replay">
        <li>Supported</li>
        <li>Inference</li>
        <li>Conflict</li>
        <li>Unsupported</li>
      </ul>
      <a
        href={getTraceUrl(runtime.demoTraceId)}
        target="_blank"
        rel="noreferrer"
        data-testid="inspect-demo-trace"
      >
        Inspect exact Trace <ExternalLink size={13} aria-hidden="true" />
      </a>
    </aside>
  );
}

interface SidebarProps {
  workspaces: readonly Workspace[];
  activeWorkspaceId: string | null;
  canvases: readonly Canvas[];
  activeCanvasId: string | null;
  collapsed: boolean;
  creating: boolean;
  runtime: RuntimeMode | null;
  onCollapse: () => void;
  onWorkspaceOpen: (workspaceId: string) => void;
  onWorkspaceCreate: () => void;
  onOpen: (canvasId: string) => void;
  onCreate: (name: string) => Promise<void>;
}

function CanvasSidebar({
  workspaces,
  activeWorkspaceId,
  canvases,
  activeCanvasId,
  collapsed,
  creating,
  runtime,
  onCollapse,
  onWorkspaceOpen,
  onWorkspaceCreate,
  onOpen,
  onCreate,
}: SidebarProps) {
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim()) {
      setError("Give your canvas a name.");
      return;
    }
    setError(null);
    try {
      await onCreate(name.trim());
      setName("");
      setShowForm(false);
    } catch (caught) {
      setError(getErrorMessage(caught));
    }
  };

  return (
    <aside className={`canvas-sidebar ${collapsed ? "canvas-sidebar--collapsed" : ""}`}>
      <div className="canvas-sidebar__brand">
        <span className="brand-mark" aria-hidden="true">
          <Sparkles size={17} />
        </span>
        {!collapsed && <strong>SolarPlexus Mobius</strong>}
        <button
          type="button"
          onClick={onCollapse}
          aria-label={collapsed ? "Expand canvas list" : "Collapse canvas list"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
        </button>
      </div>

      {!collapsed && (
        <>
          <div className="canvas-sidebar__section-title">
            <span>Workspace</span>
            <button type="button" onClick={onWorkspaceCreate} aria-label="Create workspace">
              <Plus size={15} aria-hidden="true" />
            </button>
          </div>
          {workspaces.length > 0 ? (
            <select
              className="workspace-select"
              value={activeWorkspaceId ?? ""}
              onChange={(event) => onWorkspaceOpen(event.target.value)}
              aria-label="Active workspace"
            >
              {workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
          ) : (
            <button type="button" className="workspace-empty" onClick={onWorkspaceCreate}>
              Create your first workspace
            </button>
          )}
          <div className="canvas-sidebar__section-title">
            <span>Your canvases</span>
            <button
              type="button"
              onClick={() => setShowForm((current) => !current)}
              aria-label="Create canvas"
              title="Create canvas"
              data-testid="new-canvas-button"
            >
              <Plus size={15} aria-hidden="true" />
            </button>
          </div>

          {showForm && (
            <form className="new-canvas-form" onSubmit={submit}>
              <label htmlFor="new-canvas-name">Canvas name</label>
              <input
                id="new-canvas-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Product launch"
                maxLength={120}
                autoFocus
                data-testid="new-canvas-name"
              />
              {error && <span role="alert">{error}</span>}
              <div>
                <button type="button" onClick={() => setShowForm(false)}>
                  Cancel
                </button>
                <button type="submit" disabled={creating} data-testid="create-canvas-submit">
                  {creating ? <LoaderCircle size={14} className="spin" /> : <Plus size={14} />}
                  Create
                </button>
              </div>
            </form>
          )}

          <nav className="canvas-list" aria-label="Canvases">
            {canvases.map((canvas) => (
              <button
                type="button"
                key={canvas.id}
                className={canvas.id === activeCanvasId ? "is-active" : ""}
                onClick={() => onOpen(canvas.id)}
                aria-current={canvas.id === activeCanvasId ? "page" : undefined}
                data-testid={`open-canvas-${canvas.id}`}
              >
                <FolderOpen size={15} aria-hidden="true" />
                <span>{canvas.name}</span>
              </button>
            ))}
          </nav>

          {runtime?.mode === "deterministic_replay" && (
            <DemoModeBanner runtime={runtime} placement="sidebar" />
          )}
          {runtime?.appMode === "staging" && (
            <div className="environment-indicator" role="status">
              STAGING · production-shaped data
            </div>
          )}
        </>
      )}

      <div className="canvas-sidebar__footer" title="Local-first editing with server persistence">
        <Cloud size={15} aria-hidden="true" />
        {!collapsed && <a href="/account">Account · server-synced</a>}
      </div>
    </aside>
  );
}

export function OpenCanvasApp() {
  const queryClient = useQueryClient();
  const [chosenWorkspaceId, setChosenWorkspaceId] = useState<string | null>(null);
  const [chosenCanvasId, setChosenCanvasId] = useState<string | null>(null);
  const [storedCanvasId] = useState<string | null>(() =>
    typeof window === "undefined" ? null : window.localStorage.getItem(LAST_CANVAS_KEY),
  );
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const runtimeQuery = useQuery({
    queryKey: ["runtime-mode"],
    queryFn: ({ signal }) => canvasApi.getRuntimeMode(signal),
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });

  const workspacesQuery = useQuery({
    queryKey: ["workspaces"],
    queryFn: ({ signal }) => workspaceApi.list(signal),
  });

  const activeWorkspaceId = chosenWorkspaceId ?? workspacesQuery.data?.[0]?.id ?? null;

  const canvasesQuery = useQuery({
    queryKey: ["canvases", activeWorkspaceId],
    queryFn: ({ signal }) => canvasApi.listCanvases(activeWorkspaceId ?? undefined, signal),
  });

  const activeCanvasId =
    chosenCanvasId ??
    canvasesQuery.data?.find(
      (canvas) =>
        runtimeQuery.data?.mode === "deterministic_replay" &&
        canvas.id === runtimeQuery.data.demoCanvasId,
    )?.id ??
    canvasesQuery.data?.find((canvas) => canvas.id === storedCanvasId)?.id ??
    canvasesQuery.data?.[0]?.id ??
    null;

  const snapshotQuery = useQuery({
    queryKey: ["canvas", activeCanvasId, "snapshot"],
    queryFn: ({ signal }) => canvasApi.getSnapshot(activeCanvasId ?? "", signal),
    enabled: Boolean(activeCanvasId),
  });

  const createCanvas = useMutation({
    mutationFn: (name: string) => canvasApi.createCanvas(name, activeWorkspaceId ?? undefined),
    onSuccess: (canvas) => {
      setChosenWorkspaceId(canvas.workspaceId);
      queryClient.setQueryData<Canvas[]>(["canvases", canvas.workspaceId], (current = []) => [
        ...current,
        canvas,
      ]);
      void queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      setChosenCanvasId(canvas.id);
      window.localStorage.setItem(LAST_CANVAS_KEY, canvas.id);
    },
  });

  const createWorkspace = useMutation({
    mutationFn: (name: string) => workspaceApi.create(name),
    onSuccess: (workspace) => {
      queryClient.setQueryData<Workspace[]>(["workspaces"], (current = []) => [
        ...current,
        workspace,
      ]);
      setChosenWorkspaceId(workspace.id);
      setChosenCanvasId(null);
    },
  });

  const openCanvas = (canvasId: string) => {
    if (canvasId === activeCanvasId) return;
    queryClient.removeQueries({ queryKey: ["canvas", canvasId, "snapshot"], exact: true });
    setChosenCanvasId(canvasId);
    window.localStorage.setItem(LAST_CANVAS_KEY, canvasId);
  };

  const canvases = canvasesQuery.data ?? [];

  return (
    <main className="opencanvas-app">
      <CanvasSidebar
        workspaces={workspacesQuery.data ?? []}
        activeWorkspaceId={activeWorkspaceId}
        canvases={canvases}
        activeCanvasId={activeCanvasId}
        collapsed={sidebarCollapsed}
        creating={createCanvas.isPending}
        runtime={runtimeQuery.data ?? null}
        onCollapse={() => setSidebarCollapsed((current) => !current)}
        onWorkspaceOpen={(workspaceId) => {
          setChosenWorkspaceId(workspaceId);
          setChosenCanvasId(null);
        }}
        onWorkspaceCreate={() => {
          const name = window.prompt("Workspace name", "My workspace")?.trim();
          if (name) createWorkspace.mutate(name);
        }}
        onOpen={openCanvas}
        onCreate={async (name) => {
          await createCanvas.mutateAsync(name);
        }}
      />

      <section className="opencanvas-main" aria-label="Canvas workspace">
        {canvasesQuery.isPending ? (
          <LoadingState label="Opening SolarPlexus Mobius…" />
        ) : canvasesQuery.isError ? (
          <ErrorState
            message={getErrorMessage(canvasesQuery.error)}
            onRetry={() => void canvasesQuery.refetch()}
          />
        ) : !activeCanvasId ? (
          <div className="route-state route-state--empty">
            <span className="route-state__illustration" aria-hidden="true">
              <Sparkles size={28} />
            </span>
            <p className="eyebrow">A spatial place for connected thinking</p>
            <h1>Create your first canvas</h1>
            <p>
              Add notes, draw relationships, and ask AI to reason across exactly what you select.
            </p>
            <button
              type="button"
              onClick={() => createCanvas.mutate("My first canvas")}
              disabled={createCanvas.isPending}
              data-testid="empty-create-canvas"
            >
              {createCanvas.isPending ? (
                <LoaderCircle size={16} className="spin" />
              ) : (
                <Plus size={16} />
              )}
              Create canvas
            </button>
            {createCanvas.isError && (
              <span role="alert">{getErrorMessage(createCanvas.error)}</span>
            )}
          </div>
        ) : snapshotQuery.isPending ? (
          <LoadingState label="Restoring your canvas…" />
        ) : snapshotQuery.isError || !snapshotQuery.data ? (
          <ErrorState
            message={getErrorMessage(snapshotQuery.error)}
            onRetry={() => void snapshotQuery.refetch()}
          />
        ) : (
          <ReactFlowProvider>
            <CanvasWorkspace
              key={snapshotQuery.data.canvas.id}
              snapshot={snapshotQuery.data}
              onReload={() => void snapshotQuery.refetch()}
            />
          </ReactFlowProvider>
        )}
      </section>
    </main>
  );
}

interface CanvasWorkspaceProps {
  snapshot: Awaited<ReturnType<typeof canvasApi.getSnapshot>>;
  onReload: () => void;
}

function CanvasWorkspace({ snapshot, onReload }: CanvasWorkspaceProps) {
  const flow = useReactFlow<CanvasFlowNode, CanvasFlowEdge>();
  const stageRef = useRef<HTMLDivElement>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const saveQueueRef = useRef<AutosaveQueue | null>(null);
  const saveStateRef = useRef<SaveState>({ status: "saved", savedAt: null });
  const [nodes, setNodes] = useState<CanvasFlowNode[]>(() =>
    snapshot.nodes.map((node) => toFlowNode(node)),
  );
  const [edges, setEdges] = useState<CanvasFlowEdge[]>(() => snapshot.edges.map(toFlowEdge));
  const nodesRef = useRef<CanvasFlowNode[]>(nodes);
  const edgesRef = useRef<CanvasFlowEdge[]>(edges);
  const [saveState, setSaveState] = useState<SaveState>({ status: "saved", savedAt: null });
  const [surfaceError, setSurfaceError] = useState<string | null>(null);
  const [creatingNode, setCreatingNode] = useState(false);
  const [uploadState, setUploadState] = useState<{
    fileName: string;
    current: number;
    total: number;
  } | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const [preview, setPreview] = useState<{
    document: DocumentMetadata;
    citation?: Citation;
  } | null>(null);

  const replaceNodes = useCallback((next: CanvasFlowNode[]) => {
    nodesRef.current = next;
    setNodes(next);
  }, []);

  const replaceEdges = useCallback((next: CanvasFlowEdge[]) => {
    edgesRef.current = next;
    setEdges(next);
  }, []);

  const updateDocumentReferences = useCallback(
    (document: DocumentMetadata) => {
      replaceNodes(
        nodesRef.current.map((flowNode) =>
          flowNode.data.node.document?.id === document.id
            ? {
                ...flowNode,
                data: {
                  ...flowNode.data,
                  node: { ...flowNode.data.node, document },
                },
              }
            : flowNode,
        ),
      );
      setPreview((current) =>
        current?.document.id === document.id ? { ...current, document } : current,
      );
    },
    [replaceNodes],
  );

  const processingDocumentIds = useMemo(
    () =>
      Array.from(
        new Set(
          nodes
            .map((node) => node.data.node.document)
            .filter((document) =>
              document
                ? ["uploaded", "queued", "processing", "retrying"].includes(document.status)
                : false,
            )
            .map((document) => document?.id)
            .filter((id): id is string => Boolean(id)),
        ),
      ),
    [nodes],
  );

  useEffect(() => {
    if (processingDocumentIds.length === 0) return;
    let disposed = false;
    let timer: number | undefined;

    const poll = async () => {
      const results = await Promise.allSettled(
        processingDocumentIds.map((documentId) => canvasApi.getDocument(documentId)),
      );
      if (disposed) return;
      for (const result of results) {
        if (result.status === "fulfilled") updateDocumentReferences(result.value);
      }
      timer = window.setTimeout(() => void poll(), 1_400);
    };

    timer = window.setTimeout(() => void poll(), 700);
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [processingDocumentIds, updateDocumentReferences]);

  const updateSavedNode = useCallback(
    (saved: CanvasNode) => {
      const next = nodesRef.current.map((flowNode) => {
        if (flowNode.id !== saved.id) return flowNode;
        // Only merge server-owned fields. Local content may already be newer than this response.
        return {
          ...flowNode,
          data: {
            ...flowNode.data,
            node: {
              ...flowNode.data.node,
              revision: saved.revision,
              updatedAt: saved.updatedAt,
            },
          },
        };
      });
      replaceNodes(next);
    },
    [replaceNodes],
  );

  useEffect(() => {
    const queue = new AutosaveQueue({
      save: (node) =>
        canvasApi.updateNode(snapshot.canvas.id, node.id, {
          revision: node.revision,
          title: node.title.trim() || "Untitled note",
          text: node.text,
          position: node.position,
          width: node.width,
          height: node.height,
        }),
      onSaved: updateSavedNode,
      onStateChange: (state) => {
        saveStateRef.current = state;
        setSaveState(state);
      },
    });
    saveQueueRef.current = queue;
    return () => queue.dispose();
  }, [snapshot.canvas.id, updateSavedNode]);

  const mutateNode = useCallback(
    (nodeId: string, update: (node: CanvasNode) => CanvasNode) => {
      let changed: CanvasNode | null = null;
      const next = nodesRef.current.map((flowNode) => {
        if (flowNode.id !== nodeId || flowNode.data.pending) return flowNode;
        changed = update(flowNode.data.node);
        return { ...flowNode, data: { ...flowNode.data, node: changed } };
      });
      replaceNodes(next);
      if (changed) saveQueueRef.current?.mark(changed);
    },
    [replaceNodes],
  );

  const changeTitle = useCallback(
    (nodeId: string, title: string) => mutateNode(nodeId, (node) => ({ ...node, title })),
    [mutateNode],
  );
  const changeText = useCallback(
    (nodeId: string, text: string) => {
      let groundingInvalidated = false;
      mutateNode(nodeId, (node) => {
        groundingInvalidated = node.type === "ai_response" && node.text !== text;
        return {
          ...node,
          text,
          citations: groundingInvalidated ? [] : node.citations,
        };
      });
      if (groundingInvalidated) {
        replaceEdges(removeResponseCitationEdges(edgesRef.current, nodeId));
      }
    },
    [mutateNode, replaceEdges],
  );

  const selectNode = useCallback(
    (nodeId: string, additive: boolean) => {
      replaceNodes(
        nodesRef.current.map((node) => ({
          ...node,
          selected: node.id === nodeId || (additive && Boolean(node.selected)),
        })),
      );
      if (!additive) {
        replaceEdges(edgesRef.current.map((edge) => ({ ...edge, selected: false })));
      }
    },
    [replaceEdges, replaceNodes],
  );

  const deleteNode = useCallback(
    async (nodeId: string) => {
      const pending = nodesRef.current.find((node) => node.id === nodeId)?.data.pending;
      if (pending) {
        replaceNodes(nodesRef.current.filter((node) => node.id !== nodeId));
        return;
      }

      await saveQueueRef.current?.flush();
      const beforeNodes = nodesRef.current;
      const beforeEdges = edgesRef.current;
      const current = nodesRef.current.find((node) => node.id === nodeId);
      if (!current) return;
      replaceNodes(nodesRef.current.filter((node) => node.id !== nodeId));
      replaceEdges(
        edgesRef.current.filter((edge) => edge.source !== nodeId && edge.target !== nodeId),
      );
      try {
        await canvasApi.deleteNode(snapshot.canvas.id, nodeId, current.data.node.revision);
        setSurfaceError(null);
      } catch (error) {
        replaceNodes(beforeNodes);
        replaceEdges(beforeEdges);
        setSurfaceError(getErrorMessage(error));
      }
    },
    [replaceEdges, replaceNodes, snapshot.canvas.id],
  );

  const duplicateNode = useCallback(
    async (nodeId: string) => {
      await saveQueueRef.current?.flush();
      const source = nodesRef.current.find((node) => node.id === nodeId);
      if (!source || source.data.pending) return;
      try {
        const duplicate = await canvasApi.duplicateNode(
          snapshot.canvas.id,
          nodeId,
          source.data.node.revision,
          { x: source.position.x + 38, y: source.position.y + 38 },
        );
        replaceNodes([
          ...nodesRef.current.map((node) => ({ ...node, selected: false })),
          toFlowNode(duplicate, { selected: true }),
        ]);
        setSurfaceError(null);
      } catch (error) {
        setSurfaceError(getErrorMessage(error));
      }
    },
    [replaceNodes, snapshot.canvas.id],
  );

  const previewDocument = useCallback((nodeId: string) => {
    const document = nodesRef.current.find((node) => node.id === nodeId)?.data.node.document;
    if (!document) {
      setSurfaceError("Document metadata is not available yet.");
      return;
    }
    if (document.status !== "ready") {
      setSurfaceError("Wait for document processing to finish before opening the preview.");
      return;
    }
    setPreview({ document });
  }, []);

  const openCitation = useCallback(async (citation: Citation) => {
    const local = nodesRef.current
      .map((node) => node.data.node.document)
      .find((document) => document?.id === citation.documentId);
    try {
      const document = local ?? (await canvasApi.getDocument(citation.documentId));
      setPreview({ document, citation });
      setSurfaceError(null);
    } catch (error) {
      setSurfaceError(getErrorMessage(error));
    }
  }, []);

  const retryDocument = useCallback(
    async (nodeId: string) => {
      const document = nodesRef.current.find((node) => node.id === nodeId)?.data.node.document;
      if (!document) return;
      try {
        updateDocumentReferences(await canvasApi.retryDocument(document.id));
        setSurfaceError(null);
      } catch (error) {
        setSurfaceError(getErrorMessage(error));
      }
    },
    [updateDocumentReferences],
  );

  const deleteDocument = useCallback(
    async (nodeId: string) => {
      const document = nodesRef.current.find((node) => node.id === nodeId)?.data.node.document;
      if (!document) return;
      const beforeNodes = nodesRef.current;
      const beforeEdges = edgesRef.current;
      const removedIds = new Set(
        beforeNodes
          .filter((node) => node.data.node.document?.id === document.id)
          .map((node) => node.id),
      );
      replaceNodes(
        removeDocumentCitations(
          beforeNodes.filter((node) => !removedIds.has(node.id)),
          new Set([document.id]),
        ),
      );
      replaceEdges(
        beforeEdges.filter((edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target)),
      );
      setPreview((current) => (current?.document.id === document.id ? null : current));
      try {
        await canvasApi.deleteDocument(document.id);
        setSurfaceError(null);
      } catch (error) {
        replaceNodes(beforeNodes);
        replaceEdges(beforeEdges);
        setSurfaceError(getErrorMessage(error));
      }
    },
    [replaceEdges, replaceNodes],
  );

  const handlers = useMemo<NodeHandlers>(
    () => ({
      onTitleChange: changeTitle,
      onTextChange: changeText,
      onDuplicate: (nodeId) => void duplicateNode(nodeId),
      onDelete: (nodeId) => void deleteNode(nodeId),
      onSelect: selectNode,
      onPreviewDocument: previewDocument,
      onRetryDocument: (nodeId) => void retryDocument(nodeId),
      onDeleteDocument: (nodeId) => void deleteDocument(nodeId),
      onOpenCitation: (citation) => void openCitation(citation),
    }),
    [
      changeText,
      changeTitle,
      deleteDocument,
      deleteNode,
      duplicateNode,
      openCitation,
      previewDocument,
      retryDocument,
      selectNode,
    ],
  );
  const onNodesChange = useCallback(
    (changes: NodeChange<CanvasFlowNode>[]) => {
      const changedGeometry = new Set(
        changes
          .filter((change) => change.type === "position" || change.type === "dimensions")
          .map((change) => change.id),
      );
      const applied = applyNodeChanges(changes, nodesRef.current).map((flowNode) => {
        if (!changedGeometry.has(flowNode.id) || flowNode.data.pending) return flowNode;
        const styleWidth =
          typeof flowNode.style?.width === "number" ? flowNode.style.width : undefined;
        const styleHeight =
          typeof flowNode.style?.height === "number" ? flowNode.style.height : undefined;
        const domain = {
          ...flowNode.data.node,
          position: flowNode.position,
          width:
            flowNode.width ?? flowNode.measured?.width ?? styleWidth ?? flowNode.data.node.width,
          height:
            flowNode.height ??
            flowNode.measured?.height ??
            styleHeight ??
            flowNode.data.node.height,
        };
        return { ...flowNode, data: { ...flowNode.data, node: domain } };
      });
      replaceNodes(applied);
      changedGeometry.forEach((id) => {
        const changed = applied.find((node) => node.id === id);
        if (changed && !changed.data.pending) saveQueueRef.current?.mark(changed.data.node);
      });
    },
    [replaceNodes],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange<CanvasFlowEdge>[]) => {
      replaceEdges(applyEdgeChanges(changes, edgesRef.current));
    },
    [replaceEdges],
  );

  const createConnection = useCallback(
    async (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const source = nodesRef.current.find((node) => node.id === connection.source);
      const target = nodesRef.current.find((node) => node.id === connection.target);
      if (!source || !target || source.data.pending || target.data.pending) {
        setSurfaceError("Wait for both canvas items to finish saving before connecting them.");
        return;
      }

      const tempId = temporaryId("edge");
      const timestamp = now();
      const temporary = toFlowEdge({
        id: tempId,
        canvasId: snapshot.canvas.id,
        sourceNodeId: connection.source,
        targetNodeId: connection.target,
        kind: "default",
        label: null,
        revision: 0,
        createdAt: timestamp,
        updatedAt: timestamp,
      });
      replaceEdges([...edgesRef.current, temporary]);

      try {
        const saved = await canvasApi.createEdge(snapshot.canvas.id, {
          sourceNodeId: connection.source,
          targetNodeId: connection.target,
          kind: "default",
          label: null,
        });
        replaceEdges(
          edgesRef.current.map((edge) => (edge.id === tempId ? toFlowEdge(saved) : edge)),
        );
        setSurfaceError(null);
      } catch (error) {
        replaceEdges(edgesRef.current.filter((edge) => edge.id !== tempId));
        setSurfaceError(getErrorMessage(error));
      }
    },
    [replaceEdges, snapshot.canvas.id],
  );

  const createNote = useCallback(async () => {
    if (creatingNode) return;
    setCreatingNode(true);
    setSurfaceError(null);
    const bounds = stageRef.current?.getBoundingClientRect();
    const center = flow.screenToFlowPosition({
      x: (bounds?.left ?? 0) + (bounds?.width ?? window.innerWidth) / 2,
      y: (bounds?.top ?? 0) + (bounds?.height ?? window.innerHeight) / 2,
    });
    const placementOffsets = [
      { x: 0, y: 0 },
      { x: 360, y: 0 },
      { x: -360, y: 0 },
      { x: 0, y: 280 },
      { x: 360, y: 280 },
      { x: -360, y: 280 },
    ] as const;
    const offset = placementOffsets[nodesRef.current.length % placementOffsets.length] ?? {
      x: 0,
      y: 0,
    };
    const draft = createNodeDraft({
      x: center.x - 160 + offset.x,
      y: center.y - 120 + offset.y,
    });
    const tempId = temporaryId("node");
    const timestamp = now();
    const temporary: CanvasNode = {
      id: tempId,
      canvasId: snapshot.canvas.id,
      revision: 0,
      createdAt: timestamp,
      updatedAt: timestamp,
      ...draft,
    };
    replaceNodes([
      ...nodesRef.current.map((node) => ({ ...node, selected: false })),
      toFlowNode(temporary, { pending: true, selected: true }),
    ]);

    try {
      const saved = await canvasApi.createNode(snapshot.canvas.id, draft);
      replaceNodes(
        nodesRef.current.map((node) =>
          node.id === tempId ? toFlowNode(saved, { selected: true }) : node,
        ),
      );
    } catch (error) {
      replaceNodes(nodesRef.current.filter((node) => node.id !== tempId));
      setSurfaceError(getErrorMessage(error));
    } finally {
      setCreatingNode(false);
    }
  }, [creatingNode, flow, replaceNodes, snapshot.canvas.id]);

  const uploadDocuments = useCallback(
    async (files: readonly File[]) => {
      if (files.length === 0 || uploadState) return;
      const invalid = files.find(
        (file) => !SUPPORTED_DOCUMENT_EXTENSIONS.has(documentExtension(file.name)),
      );
      if (invalid) {
        setSurfaceError(
          `${invalid.name} is not supported. Upload a PDF, TXT, Markdown, or DOCX file.`,
        );
        return;
      }
      const empty = files.find((file) => file.size === 0);
      if (empty) {
        setSurfaceError(`${empty.name} is empty and cannot be processed.`);
        return;
      }
      const oversized = files.find((file) => file.size > CLIENT_DOCUMENT_SIZE_LIMIT);
      if (oversized) {
        setSurfaceError(`${oversized.name} exceeds the 25 MB upload limit.`);
        return;
      }

      setSurfaceError(null);
      const bounds = stageRef.current?.getBoundingClientRect();
      const center = flow.screenToFlowPosition({
        x: (bounds?.left ?? 0) + (bounds?.width ?? window.innerWidth) / 2,
        y: (bounds?.top ?? 0) + (bounds?.height ?? window.innerHeight) / 2,
      });

      for (const [index, file] of files.entries()) {
        const fileType = documentFileType(file.name);
        if (!fileType) continue;
        setUploadState({ fileName: file.name, current: index + 1, total: files.length });
        const tempNodeId = temporaryId("document-node");
        const tempDocumentId = temporaryId("document");
        const timestamp = now();
        const position = {
          x: center.x - 170 + ((nodesRef.current.length + index) % 3) * 34,
          y: center.y - 140 + ((nodesRef.current.length + index) % 3) * 34,
        };
        const temporaryDocument: DocumentMetadata = {
          id: tempDocumentId,
          canvasId: snapshot.canvas.id,
          fileName: file.name,
          fileType,
          mediaType: file.type || "application/octet-stream",
          fileSize: file.size,
          pageCount: null,
          status: "processing",
          processingStage: "uploading",
          errorMessage: null,
          chunkCount: 0,
          createdAt: timestamp,
          updatedAt: timestamp,
        };
        const temporaryNode: CanvasNode = {
          id: tempNodeId,
          canvasId: snapshot.canvas.id,
          type: "document",
          title: file.name,
          text: "",
          position,
          width: 340,
          height: 280,
          revision: 0,
          document: temporaryDocument,
          createdAt: timestamp,
          updatedAt: timestamp,
        };
        replaceNodes([
          ...nodesRef.current.map((node) => ({ ...node, selected: false })),
          toFlowNode(temporaryNode, { pending: true, selected: true }),
        ]);

        try {
          const result = await canvasApi.uploadDocument(snapshot.canvas.id, file, position);
          const savedNode: CanvasNode = {
            ...result.node,
            document: result.node.document ?? result.document,
          };
          replaceNodes(
            nodesRef.current.map((node) =>
              node.id === tempNodeId ? toFlowNode(savedNode, { selected: true }) : node,
            ),
          );
        } catch (error) {
          replaceNodes(nodesRef.current.filter((node) => node.id !== tempNodeId));
          setSurfaceError(getErrorMessage(error));
          break;
        }
      }
      setUploadState(null);
    },
    [flow, replaceNodes, snapshot.canvas.id, uploadState],
  );

  const chooseDocuments = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files ?? []);
      event.target.value = "";
      void uploadDocuments(files);
    },
    [uploadDocuments],
  );

  const dropDocuments = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDropActive(false);
      void uploadDocuments(Array.from(event.dataTransfer.files));
    },
    [uploadDocuments],
  );

  const deleteSelection = useCallback(async () => {
    await saveQueueRef.current?.flush();
    const selectedNodes = nodesRef.current.filter((node) => node.selected && !node.data.pending);
    const selectedEdges = edgesRef.current.filter((edge) => edge.selected);
    const beforeNodes = nodesRef.current;
    const beforeEdges = edgesRef.current;
    const selectedDocumentIds = new Set(
      selectedNodes
        .map((node) => node.data.node.document?.id)
        .filter((id): id is string => Boolean(id)),
    );
    const selectedNodeIds = new Set(
      beforeNodes
        .filter(
          (node) =>
            selectedNodes.some((selected) => selected.id === node.id) ||
            (node.data.node.document?.id
              ? selectedDocumentIds.has(node.data.node.document.id)
              : false),
        )
        .map((node) => node.id),
    );

    replaceNodes(
      removeDocumentCitations(
        beforeNodes.filter((node) => !selectedNodeIds.has(node.id)),
        selectedDocumentIds,
      ),
    );
    replaceEdges(
      beforeEdges.filter(
        (edge) =>
          !edge.selected && !selectedNodeIds.has(edge.source) && !selectedNodeIds.has(edge.target),
      ),
    );

    try {
      for (const edge of selectedEdges) {
        const domain = edge.data?.edge;
        if (domain && !edge.id.startsWith("temp-")) {
          await canvasApi.deleteEdge(snapshot.canvas.id, edge.id, domain.revision);
        }
      }
      for (const documentId of selectedDocumentIds) {
        await canvasApi.deleteDocument(documentId);
      }
      for (const node of selectedNodes.filter((node) => node.data.node.type !== "document")) {
        await canvasApi.deleteNode(snapshot.canvas.id, node.id, node.data.node.revision);
      }
      setPreview((current) =>
        current && selectedDocumentIds.has(current.document.id) ? null : current,
      );
      setSurfaceError(null);
    } catch (error) {
      replaceNodes(beforeNodes);
      replaceEdges(beforeEdges);
      setSurfaceError(getErrorMessage(error));
    }
  }, [replaceEdges, replaceNodes, snapshot.canvas.id]);

  const flush = useCallback(async () => {
    await saveQueueRef.current?.flush();
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const saveShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s";
      if (saveShortcut) {
        event.preventDefault();
        void flush();
        return;
      }
      if (
        (event.key === "Delete" || event.key === "Backspace") &&
        !isEditableTarget(event.target)
      ) {
        event.preventDefault();
        void deleteSelection();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [deleteSelection, flush]);

  const selected = useMemo(() => selectedCanvasNodes(nodes), [nodes]);

  const clearSelection = useCallback(() => {
    replaceNodes(nodesRef.current.map((node) => ({ ...node, selected: false })));
    replaceEdges(edgesRef.current.map((edge) => ({ ...edge, selected: false })));
  }, [replaceEdges, replaceNodes]);

  const askAI = useCallback(
    async (instruction: string) => {
      await flush();
      if (saveStateRef.current.status === "error") {
        throw new Error("Save your latest note changes before asking the assistant.");
      }
      const context = selectedCanvasNodes(nodesRef.current);
      const request = buildAIRequest(instruction, context);
      const result = await canvasApi.askAI(snapshot.canvas.id, request);
      const responseNode: CanvasNode = {
        ...result.node,
        citations: result.node.citations ?? result.citations,
      };
      replaceNodes([
        ...nodesRef.current.map((node) => ({ ...node, selected: false })),
        toFlowNode(responseNode, { selected: true }),
      ]);
      replaceEdges(upsertFlowEdges(edgesRef.current, result.edges.map(toFlowEdge)));
      window.setTimeout(() => {
        void flow.fitView({ nodes: [{ id: result.node.id }], duration: 420, padding: 0.7 });
      }, 0);
      setSurfaceError(null);
      return {
        mock: result.mock,
        grounded: result.grounded,
        insufficientEvidence: result.insufficientEvidence,
      };
    },
    [flow, flush, replaceEdges, replaceNodes, snapshot.canvas.id],
  );

  const connectSelected = useCallback(() => {
    const [source, target] = selectedCanvasNodes(nodesRef.current);
    if (!source || !target) return;
    void createConnection({
      source: source.id,
      target: target.id,
      sourceHandle: null,
      targetHandle: null,
    });
  }, [createConnection]);

  return (
    <div className="canvas-workspace">
      <div
        className={`canvas-stage ${dropActive ? "canvas-stage--drop-active" : ""}`}
        ref={stageRef}
        onDragEnter={(event) => {
          if (event.dataTransfer.types.includes("Files")) {
            event.preventDefault();
            setDropActive(true);
          }
        }}
        onDragOver={(event) => {
          if (event.dataTransfer.types.includes("Files")) event.preventDefault();
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setDropActive(false);
          }
        }}
        onDrop={dropDocuments}
      >
        <header className="canvas-toolbar" aria-label="Canvas toolbar">
          <div className="canvas-toolbar__title">
            <span>{snapshot.canvas.name}</span>
            <small>
              {nodes.length} {nodes.length === 1 ? "node" : "nodes"}
            </small>
          </div>
          <span className={`save-indicator save-indicator--${saveState.status}`} aria-live="polite">
            {saveState.status === "saving" && <LoaderCircle size={13} className="spin" />}
            {saveState.status === "saved" && <Check size={13} />}
            {saveState.status === "dirty" && <Cloud size={13} />}
            {saveState.status === "error" && <CloudOff size={13} />}
            {saveState.status === "saving"
              ? "Saving"
              : saveState.status === "dirty"
                ? "Unsaved"
                : saveState.status === "error"
                  ? "Save failed"
                  : "Saved"}
          </span>
          <div className="canvas-toolbar__actions">
            {selected.length === 2 && (
              <button type="button" onClick={connectSelected} data-testid="connect-selected">
                <ArrowRight size={15} aria-hidden="true" /> Connect
              </button>
            )}
            <button
              type="button"
              onClick={() => void flush()}
              title="Save now (Ctrl/⌘ + S)"
              aria-label="Save canvas"
              data-testid="save-canvas"
            >
              <Save size={15} aria-hidden="true" /> Save
            </button>
            <input
              ref={uploadInputRef}
              className="visually-hidden"
              type="file"
              accept=".pdf,.txt,.md,.markdown,.docx"
              multiple
              onChange={chooseDocuments}
              aria-label="Choose documents to upload"
              data-testid="document-file-input"
            />
            <button
              type="button"
              onClick={() => uploadInputRef.current?.click()}
              disabled={Boolean(uploadState)}
              aria-label="Upload documents"
              data-testid="upload-document"
            >
              {uploadState ? (
                <LoaderCircle size={15} className="spin" aria-hidden="true" />
              ) : (
                <Upload size={15} aria-hidden="true" />
              )}
              {uploadState ? "Uploading" : "Upload"}
            </button>
            <button
              type="button"
              className="canvas-toolbar__primary"
              onClick={() => void createNote()}
              disabled={creatingNode}
              data-testid="add-note"
            >
              {creatingNode ? <LoaderCircle size={15} className="spin" /> : <Plus size={15} />}
              Add note
            </button>
          </div>
        </header>

        <CanvasNodeActionsProvider actions={handlers}>
          <ReactFlow<CanvasFlowNode, CanvasFlowEdge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={(connection) => void createConnection(connection)}
            defaultViewport={snapshot.canvas.viewport}
            minZoom={0.18}
            maxZoom={2.5}
            snapToGrid
            snapGrid={[12, 12]}
            selectionOnDrag
            selectionMode={SelectionMode.Partial}
            multiSelectionKeyCode="Shift"
            deleteKeyCode={null}
            panOnDrag={[1, 2]}
            fitView={snapshot.nodes.length > 0}
            fitViewOptions={{ padding: 0.25, maxZoom: 1 }}
            aria-label="SolarPlexus Mobius spatial editor"
            colorMode="dark"
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.1} color="#34373b" />
            <Controls showInteractive={false} position="bottom-left" />
            <MiniMap
              position="bottom-right"
              pannable
              zoomable
              nodeColor={(node) =>
                (node as CanvasFlowNode).data.node.type === "ai_response"
                  ? "#9f87ef"
                  : (node as CanvasFlowNode).data.node.type === "document"
                    ? "#61c4d6"
                    : "#c5e982"
              }
              maskColor="rgba(5, 6, 8, 0.7)"
            />
          </ReactFlow>
        </CanvasNodeActionsProvider>

        {dropActive && (
          <div className="document-dropzone" role="status" aria-live="polite">
            <Upload size={26} aria-hidden="true" />
            <strong>Drop documents onto this canvas</strong>
            <span>PDF, TXT, Markdown, or DOCX · up to 25 MB each</span>
          </div>
        )}

        {uploadState && (
          <div className="upload-status" role="status" data-testid="upload-status">
            <LoaderCircle size={15} className="spin" aria-hidden="true" />
            <span>
              Uploading {uploadState.fileName} ({uploadState.current}/{uploadState.total})
            </span>
          </div>
        )}

        {nodes.length === 0 && (
          <div className="canvas-empty" data-testid="empty-canvas">
            <span aria-hidden="true">
              <StickyNote size={24} />
            </span>
            <h2>Start with a thought</h2>
            <p>Add a note or upload a source, then ask AI to reason across your selection.</p>
            <button type="button" onClick={() => void createNote()}>
              <Plus size={15} aria-hidden="true" /> Add a note
            </button>
          </div>
        )}

        {surfaceError && (
          <div className="surface-error" role="alert">
            <CircleAlert size={15} aria-hidden="true" />
            <span>{surfaceError}</span>
            <button type="button" onClick={() => setSurfaceError(null)} aria-label="Dismiss error">
              ×
            </button>
            <button type="button" onClick={onReload}>
              Reload
            </button>
          </div>
        )}
      </div>

      {preview && (
        <DocumentPreviewPanel
          document={preview.document}
          citation={preview.citation}
          onClose={() => setPreview(null)}
        />
      )}

      <AssistantPanel selectedNodes={selected} onAsk={askAI} onClearSelection={clearSelection} />
    </div>
  );
}
