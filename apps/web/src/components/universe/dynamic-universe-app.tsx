"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity as ActivityIcon,
  ArrowLeft,
  Box,
  Check,
  CircleAlert,
  Download,
  ExternalLink,
  FileSearch,
  Filter,
  GitBranch,
  LoaderCircle,
  Orbit,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { ConfirmationDialog } from "./confirmation-dialog";
import { UniverseGraph } from "./universe-graph";
import { WorkflowDag } from "./workflow-dag";
import {
  APIError,
  canvasApi,
  getErrorMessage,
  getTraceUrl,
  universeApi,
  workspaceApi,
} from "@/lib/api-client";
import { isWorkflowTerminal, normalizeActivity, safeShortId } from "@/lib/dynamic-universe";
import type { EvidenceBundle, WorkflowStep } from "@/lib/universe-contracts";

type Panel = "universe" | "workflow" | "evidence" | "activity";
type Confirmation =
  | { kind: "approval"; step: WorkflowStep; decision: "approved" | "denied" }
  | { kind: "cancel" }
  | null;

const PAGE_SIZE = 100;
const ACTIVITY_PAGE_SIZE = 30;

function Status({
  kind = "status",
  children,
}: {
  kind?: "status" | "error";
  children: React.ReactNode;
}) {
  return (
    <div
      className={`universe-status universe-status--${kind}`}
      role={kind === "error" ? "alert" : "status"}
    >
      {kind === "error" ? <CircleAlert size={16} /> : <LoaderCircle size={16} className="spin" />}
      <span>{children}</span>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="universe-empty">{children}</div>;
}

function SelectedContext({
  nodes,
  selectedIds,
  onToggle,
}: {
  nodes: readonly { id: string; title: string; type: string }[];
  selectedIds: ReadonlySet<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <section aria-labelledby="selected-context-heading">
      <div className="universe-panel__heading">
        <div>
          <small>Authority boundary</small>
          <h2 id="selected-context-heading">Selected context</h2>
        </div>
        <strong>{selectedIds.size}/50</strong>
      </div>
      <p className="universe-help">
        Only explicit selection changes context. Relationships and visual proximity never do.
      </p>
      <ul className="universe-resource-list" aria-label="Accessible resource and context list">
        {nodes.map((node) => {
          const selected = selectedIds.has(node.id);
          return (
            <li key={node.id}>
              <span>
                <small>{node.type.replaceAll("_", " ")}</small>
                <strong>{node.title}</strong>
              </span>
              <button
                type="button"
                aria-pressed={selected}
                onClick={() => onToggle(node.id)}
                disabled={!selected && selectedIds.size >= 50}
              >
                {selected ? <X size={14} /> : <Check size={14} />}
                {selected ? "Remove" : "Select"}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function DynamicUniverseApp({
  requestedWorkspaceId,
  requestedCanvasId,
  requestedWorkflowExecutionId,
  requestedRetrievalId,
  requestedBundleId,
}: {
  requestedWorkspaceId?: string;
  requestedCanvasId?: string;
  requestedWorkflowExecutionId?: string;
  requestedRetrievalId?: string;
  requestedBundleId?: string;
}) {
  const queryClient = useQueryClient();
  const [panel, setPanel] = useState<Panel>("universe");
  const [search, setSearch] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [contextTouched, setContextTouched] = useState(false);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [focusedStepId, setFocusedStepId] = useState<string | null>(null);
  const [showHistorical, setShowHistorical] = useState(false);
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [generatedBundle, setGeneratedBundle] = useState<EvidenceBundle | null>(null);

  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: ({ signal }) => workspaceApi.list(signal),
  });
  const workspaceId = workspaces.data?.some((workspace) => workspace.id === requestedWorkspaceId)
    ? (requestedWorkspaceId ?? null)
    : (workspaces.data?.[0]?.id ?? null);
  const canvases = useQuery({
    queryKey: ["canvases", workspaceId],
    queryFn: ({ signal }) => canvasApi.listCanvases(workspaceId ?? undefined, signal),
    enabled: Boolean(workspaceId),
  });
  const canvasId = canvases.data?.some((canvas) => canvas.id === requestedCanvasId)
    ? (requestedCanvasId ?? null)
    : (canvases.data?.[0]?.id ?? null);

  const viewport = useInfiniteQuery({
    queryKey: ["universe", workspaceId, canvasId, [...selectedIds].sort()],
    initialPageParam: undefined as { cursor: string; revision: number } | undefined,
    queryFn: ({ pageParam, signal }) =>
      universeApi.getViewport(canvasId ?? "", {
        limit: PAGE_SIZE,
        cursor: pageParam?.cursor,
        expectedCanvasRevision: pageParam?.revision,
        selectionIds: [...selectedIds],
        signal,
      }),
    getNextPageParam: (page) =>
      page.nextCursor ? { cursor: page.nextCursor, revision: page.canvasRevision } : undefined,
    enabled: Boolean(canvasId),
    retry: (count, error) => !(error instanceof APIError && error.status === 409) && count < 1,
  });

  const mergedViewport = useMemo(() => {
    const pages = viewport.data?.pages;
    const first = pages?.at(0);
    if (!pages?.length || !first) return null;
    const nodes = new Map(pages.flatMap((page) => page.nodes).map((node) => [node.id, node]));
    const edges = new Map(pages.flatMap((page) => page.edges).map((edge) => [edge.id, edge]));
    const boundaries = new Map(
      pages.flatMap((page) => page.boundaryNodes).map((node) => [node.id, node]),
    );
    const selected = new Map(
      pages.flatMap((page) => page.selectedNodes).map((node) => [node.id, node]),
    );
    return {
      ...first,
      nodes: [...nodes.values()],
      edges: [...edges.values()],
      boundaryNodes: [...boundaries.values()].filter((node) => !nodes.has(node.id)),
      selectedNodes: [...selected.values()],
      nextCursor: pages.at(-1)?.nextCursor ?? null,
      bounded: pages.some((page) => page.bounded),
    };
  }, [viewport.data]);

  const activity = useInfiniteQuery({
    queryKey: ["universe-activity", workspaceId, canvasId],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      universeApi.getActivity(workspaceId ?? "", canvasId ?? "", {
        limit: ACTIVITY_PAGE_SIZE,
        offset: pageParam,
        signal,
      }),
    getNextPageParam: (page, pages) =>
      page.length === ACTIVITY_PAGE_SIZE ? pages.length * ACTIVITY_PAGE_SIZE : undefined,
    enabled: Boolean(workspaceId && canvasId),
    refetchInterval: panel === "activity" ? 15_000 : false,
  });
  const activityRows = useMemo(() => {
    return normalizeActivity(activity.data?.pages.flat() ?? []);
  }, [activity.data]);

  const discoveredWorkflowId =
    requestedWorkflowExecutionId ??
    activityRows.find((event) => event.subjectKind === "workflow_execution")?.subjectId;
  const workflow = useQuery({
    queryKey: ["universe-workflow", workspaceId, canvasId, discoveredWorkflowId],
    queryFn: ({ signal }) =>
      universeApi.getWorkflow(
        workspaceId ?? "",
        canvasId ?? "",
        discoveredWorkflowId ?? "",
        signal,
      ),
    enabled: Boolean(workspaceId && canvasId && discoveredWorkflowId),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data && !isWorkflowTerminal(data.status) ? 5_000 : false;
    },
  });
  const discoveredRetrievalId =
    requestedRetrievalId ??
    workflow.data?.steps.find((step) => step.retrievalId)?.retrievalId ??
    undefined;
  const retrieval = useQuery({
    queryKey: ["universe-retrieval", workspaceId, canvasId, discoveredRetrievalId],
    queryFn: ({ signal }) =>
      universeApi.getRetrieval(
        workspaceId ?? "",
        canvasId ?? "",
        discoveredRetrievalId ?? "",
        signal,
      ),
    enabled: Boolean(workspaceId && canvasId && discoveredRetrievalId),
  });
  const retrievalTrace = useQuery({
    queryKey: ["universe-retrieval-trace", workspaceId, canvasId, discoveredRetrievalId],
    queryFn: ({ signal }) =>
      universeApi.getRetrievalTrace(
        workspaceId ?? "",
        canvasId ?? "",
        discoveredRetrievalId ?? "",
        signal,
      ),
    enabled: Boolean(workspaceId && canvasId && discoveredRetrievalId && panel === "evidence"),
  });
  const knownBundleId =
    requestedBundleId ??
    generatedBundle?.bundleId ??
    workflow.data?.steps.find((step) => step.evidenceBundleId)?.evidenceBundleId ??
    undefined;
  const bundle = useQuery({
    queryKey: ["universe-bundle", workspaceId, canvasId, knownBundleId],
    queryFn: ({ signal }) =>
      universeApi.getBundle(workspaceId ?? "", canvasId ?? "", knownBundleId ?? "", signal),
    enabled: Boolean(workspaceId && canvasId && knownBundleId),
  });

  const relationships = useQuery({
    queryKey: ["universe-relationships", workspaceId, canvasId, focusedId, showHistorical],
    queryFn: ({ signal }) =>
      universeApi.getRelationships(workspaceId ?? "", canvasId ?? "", focusedId ?? "", {
        includeInactive: showHistorical,
        limit: 100,
        signal,
      }),
    enabled: Boolean(workspaceId && canvasId && focusedId),
    retry: false,
  });

  const apa = useMutation({
    mutationFn: () =>
      universeApi.renderApa(workspaceId ?? "", canvasId ?? "", discoveredRetrievalId ?? ""),
  });
  const approval = useMutation({
    mutationFn: ({ step, decision }: { step: WorkflowStep; decision: "approved" | "denied" }) =>
      universeApi.decideApproval(
        workspaceId ?? "",
        canvasId ?? "",
        workflow.data?.executionId ?? "",
        step.stepExecutionId,
        decision,
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(
        ["universe-workflow", workspaceId, canvasId, data.executionId],
        data,
      );
      setNotice("The authoritative workflow state was refreshed.");
      setConfirmation(null);
      void activity.refetch();
    },
    onError: (error) => {
      setNotice(getErrorMessage(error));
      void workflow.refetch();
    },
  });
  const cancellation = useMutation({
    mutationFn: () =>
      universeApi.cancelWorkflow(
        workspaceId ?? "",
        canvasId ?? "",
        workflow.data?.executionId ?? "",
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(
        ["universe-workflow", workspaceId, canvasId, data.executionId],
        data,
      );
      setNotice("Cancellation was requested. Completed evidence and committed effects remain.");
      setConfirmation(null);
      void activity.refetch();
    },
    onError: (error) => {
      setNotice(getErrorMessage(error));
      void workflow.refetch();
    },
  });
  const generateBundle = useMutation({
    mutationFn: () =>
      universeApi.generateBundle(workspaceId ?? "", canvasId ?? "", discoveredRetrievalId ?? ""),
    onSuccess: (data) => {
      setGeneratedBundle(data);
      setNotice("The authority-filtered evidence bundle is ready.");
    },
    onError: (error) => setNotice(getErrorMessage(error)),
  });
  const downloadBundle = useMutation({
    mutationFn: () =>
      universeApi.downloadBundle(workspaceId ?? "", canvasId ?? "", knownBundleId ?? ""),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `mobius-evidence-${knownBundleId}.zip`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setNotice("The authorized evidence bundle download started.");
    },
    onError: (error) => setNotice(getErrorMessage(error)),
  });

  const displayedSelectedIds =
    !contextTouched && workflow.data ? new Set(workflow.data.selectedObjectIds) : selectedIds;
  const toggleContext = (id: string) => {
    setContextTouched(true);
    setSelectedIds((current) => {
      const next = new Set(
        !contextTouched && workflow.data ? workflow.data.selectedObjectIds : current,
      );
      if (next.has(id)) next.delete(id);
      else if (next.size < 50) next.add(id);
      return next;
    });
  };
  const allResourceRows = useMemo(() => {
    const rows = new Map<string, { id: string; title: string; type: string }>(
      [...(mergedViewport?.nodes ?? []), ...(mergedViewport?.selectedNodes ?? [])].map((node) => [
        node.id,
        { id: node.id, title: node.title, type: node.type },
      ]),
    );
    workflow.data?.selectedObjectIds.forEach((id) => {
      if (!rows.has(id))
        rows.set(id, { id, title: `Canonical resource ${safeShortId(id)}`, type: "canonical" });
    });
    return [...rows.values()].sort((left, right) => left.title.localeCompare(right.title));
  }, [mergedViewport, workflow.data]);

  if (workspaces.isPending || canvases.isPending || viewport.isPending) {
    return (
      <main className="universe-route">
        <Status>Opening the bounded Dynamic Universe…</Status>
      </main>
    );
  }
  const routeError = workspaces.error ?? canvases.error ?? viewport.error;
  if (routeError || !workspaceId || !canvasId || !mergedViewport) {
    return (
      <main className="universe-route">
        <div className="universe-route-error" role="alert">
          <CircleAlert size={24} />
          <h1>The Dynamic Universe could not open</h1>
          <p>{getErrorMessage(routeError)}</p>
          <Link href="/">Return to canvas</Link>
        </div>
      </main>
    );
  }

  const focusedStep = workflow.data?.steps.find((step) => step.stepExecutionId === focusedStepId);
  const focusedCitation = retrieval.data?.citations.find(
    (citation) => citation.canonicalObjectId === focusedId,
  );
  const activeBundle = bundle.data ?? generatedBundle;
  const canCancel =
    workflow.data &&
    !isWorkflowTerminal(workflow.data.status) &&
    !["cancel_requested", "canceling", "compensating"].includes(workflow.data.status);

  return (
    <main className="universe-route">
      <header className="universe-header">
        <div>
          <Link href="/" className="universe-back">
            <ArrowLeft size={15} /> Canvas
          </Link>
          <span className="universe-brand">
            <Sparkles size={17} aria-hidden="true" /> SolarPlexus Mobius
          </span>
          <h1>Dynamic Universe</h1>
          <p>
            {mergedViewport.canvas.name} · canvas revision {mergedViewport.canvasRevision} · graph
            revision {mergedViewport.graphRevision}
          </p>
        </div>
        <nav aria-label="Universe views">
          {(
            [
              ["universe", Orbit, "Universe"],
              ["workflow", GitBranch, "Workflow"],
              ["evidence", FileSearch, "Evidence"],
              ["activity", ActivityIcon, "Activity"],
            ] as const
          ).map(([value, Icon, label]) => (
            <button
              key={value}
              type="button"
              aria-current={panel === value ? "page" : undefined}
              onClick={() => setPanel(value)}
            >
              <Icon size={15} aria-hidden="true" /> {label}
            </button>
          ))}
        </nav>
      </header>

      {notice && (
        <div className="universe-notice" role="status">
          <span>{notice}</span>
          <button type="button" aria-label="Dismiss notice" onClick={() => setNotice(null)}>
            <X size={14} />
          </button>
        </div>
      )}

      <div className="universe-layout">
        <section className="universe-stage">
          {panel === "universe" && (
            <>
              <div className="universe-toolbar">
                <label>
                  <Search size={15} aria-hidden="true" />
                  <span className="sr-only">Search loaded resources</span>
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search loaded resources"
                  />
                </label>
                <label className="universe-check">
                  <input
                    type="checkbox"
                    checked={showHistorical}
                    onChange={(event) => setShowHistorical(event.target.checked)}
                  />
                  <Filter size={14} aria-hidden="true" /> Historical relationships
                </label>
                <button
                  type="button"
                  onClick={() => void viewport.refetch()}
                  aria-label="Refresh authoritative viewport"
                >
                  <RefreshCw size={14} /> Refresh
                </button>
              </div>
              <UniverseGraph
                viewport={mergedViewport}
                relationships={relationships.data ?? []}
                selectedIds={displayedSelectedIds}
                search={search}
                focusedObject={
                  focusedCitation
                    ? {
                        id: focusedCitation.canonicalObjectId,
                        label: focusedCitation.sourceTitle,
                        kind: focusedCitation.sourceType,
                      }
                    : focusedId
                      ? {
                          id: focusedId,
                          label: `Canonical resource ${safeShortId(focusedId)}`,
                          kind: "canonical",
                        }
                      : undefined
                }
                onToggleContext={toggleContext}
                onFocus={setFocusedId}
              />
              {viewport.hasNextPage && (
                <button
                  className="universe-load-more"
                  type="button"
                  disabled={viewport.isFetchingNextPage}
                  onClick={() => void viewport.fetchNextPage()}
                >
                  {viewport.isFetchingNextPage ? "Loading…" : "Load next bounded region page"}
                </button>
              )}
            </>
          )}

          {panel === "workflow" &&
            (workflow.isPending ? (
              <Status>Loading controlled workflow state…</Status>
            ) : workflow.isError ? (
              <Status kind="error">{getErrorMessage(workflow.error)}</Status>
            ) : workflow.data ? (
              <>
                <div className="workflow-summary">
                  <div>
                    <small>Authoritative execution</small>
                    <h2>{workflow.data.status.replaceAll("_", " ")}</h2>
                    <p>
                      Version {safeShortId(workflow.data.versionId)} · outcome{" "}
                      {workflow.data.outcome?.replaceAll("_", " ") ?? "pending"}
                    </p>
                  </div>
                  {canCancel && (
                    <button
                      type="button"
                      className="danger-button"
                      onClick={() => setConfirmation({ kind: "cancel" })}
                    >
                      Cancel workflow
                    </button>
                  )}
                </div>
                <WorkflowDag execution={workflow.data} onFocusStep={setFocusedStepId} />
              </>
            ) : (
              <Empty>
                <GitBranch size={26} />
                <h2>No controlled workflow selected</h2>
                <p>
                  Open this route with a scoped <code>workflowExecutionId</code>, or wait for
                  workflow activity in this canvas.
                </p>
              </Empty>
            ))}

          {panel === "evidence" &&
            (retrieval.isPending ? (
              <Status>Loading retrieval evidence…</Status>
            ) : retrieval.isError ? (
              <Status kind="error">{getErrorMessage(retrieval.error)}</Status>
            ) : retrieval.data ? (
              <div className="evidence-view">
                <section
                  className={`retrieval-outcome retrieval-outcome--${retrieval.data.outcome}`}
                >
                  <small>Authoritative retrieval outcome</small>
                  <h2>{retrieval.data.outcome.replaceAll("_", " ")}</h2>
                  <p>
                    Graph revision {retrieval.data.graphRevision} ·{" "}
                    {retrieval.data.algorithmVersion}
                  </p>
                  {retrieval.data.bounded && (
                    <strong>Bounded result — traversal or context limits were reached.</strong>
                  )}
                </section>
                <section>
                  <div className="universe-panel__heading">
                    <h2>Inclusion and exclusion decisions</h2>
                    <span>{retrieval.data.decisions.length}</span>
                  </div>
                  <ol className="evidence-decisions">
                    {retrieval.data.decisions.map((decision) => (
                      <li
                        key={decision.decisionId}
                        className={decision.included ? "is-included" : "is-excluded"}
                      >
                        <strong>{decision.included ? "Included" : "Excluded"}</strong>
                        <span>{decision.reasonCode.replaceAll("_", " ")}</span>
                        <small>
                          distance {decision.distance}
                          {decision.rank ? ` · rank ${decision.rank}` : ""} · path{" "}
                          {decision.relationshipPath.length || "none"}
                        </small>
                      </li>
                    ))}
                  </ol>
                </section>
                <section>
                  <div className="universe-panel__heading">
                    <h2>Exact citations</h2>
                    <span>{retrieval.data.citations.length}</span>
                  </div>
                  {retrieval.data.citations.length ? (
                    <ol className="citation-list">
                      {retrieval.data.citations.map((citation) => (
                        <li key={citation.citationId}>
                          <button
                            type="button"
                            onClick={() => {
                              setFocusedId(citation.canonicalObjectId);
                              setPanel("universe");
                            }}
                          >
                            <strong>
                              [{citation.ordinal}] {citation.sourceTitle}
                            </strong>
                            <span>{citation.excerpt}</span>
                            <small>
                              source v{citation.sourceVersion} · canonical v
                              {citation.canonicalVersion}
                            </small>
                          </button>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p>No citation was produced. The interface does not fabricate one.</p>
                  )}
                  <button type="button" disabled={apa.isPending} onClick={() => apa.mutate()}>
                    Render APA 7 citations
                  </button>
                  {apa.isError && <span role="alert">{getErrorMessage(apa.error)}</span>}
                  {apa.data && (
                    <ol className="apa-list">
                      {apa.data.citations.map((citation) => (
                        <li key={citation.citationId}>
                          <span>{citation.inText}</span>
                          <p>{citation.reference}</p>
                        </li>
                      ))}
                    </ol>
                  )}
                </section>
              </div>
            ) : (
              <Empty>
                <FileSearch size={26} />
                <h2>No retrieval evidence selected</h2>
                <p>A retrieval ID may be supplied directly or discovered from a workflow step.</p>
              </Empty>
            ))}

          {panel === "activity" &&
            (activity.isPending ? (
              <Status>Loading scoped activity…</Status>
            ) : activity.isError ? (
              <Status kind="error">{getErrorMessage(activity.error)}</Status>
            ) : activityRows.length ? (
              <section className="activity-timeline" aria-labelledby="activity-heading">
                <div className="universe-panel__heading">
                  <div>
                    <small>Canvas scope · newest first</small>
                    <h2 id="activity-heading">Activity timeline</h2>
                  </div>
                  <span>{activityRows.length} loaded</span>
                </div>
                <ol>
                  {activityRows.map((event) => (
                    <li key={event.eventId}>
                      <span className={`activity-dot activity-dot--${event.status}`} />
                      <div>
                        <strong>{event.eventType.replaceAll(".", " · ")}</strong>
                        <p>
                          {event.subjectKind.replaceAll("_", " ")} · {safeShortId(event.subjectId)}
                        </p>
                        <small>
                          sequence {event.sequence} ·{" "}
                          <time dateTime={event.occurredAt}>
                            {new Date(event.occurredAt).toLocaleString()}
                          </time>{" "}
                          · {event.status.replaceAll("_", " ")}
                        </small>
                      </div>
                    </li>
                  ))}
                </ol>
                {activity.hasNextPage && (
                  <button
                    type="button"
                    disabled={activity.isFetchingNextPage}
                    onClick={() => void activity.fetchNextPage()}
                  >
                    {activity.isFetchingNextPage ? "Loading…" : "Load older activity"}
                  </button>
                )}
              </section>
            ) : (
              <Empty>
                <ActivityIcon size={26} />
                <h2>No projected activity</h2>
                <p>This bounded canvas timeline is currently empty.</p>
              </Empty>
            ))}
        </section>

        <aside className="universe-inspector" aria-label="Universe inspector">
          {panel === "universe" && (
            <>
              <SelectedContext
                nodes={allResourceRows}
                selectedIds={displayedSelectedIds}
                onToggle={toggleContext}
              />
              <section aria-labelledby="relationship-heading">
                <div className="universe-panel__heading">
                  <h2 id="relationship-heading">References</h2>
                  <span>{relationships.data?.length ?? 0}</span>
                </div>
                {!focusedId ? (
                  <p>Focus a resource to load its scoped relationships.</p>
                ) : relationships.isPending ? (
                  <Status>Loading references…</Status>
                ) : relationships.isError ? (
                  <p role="alert">
                    This resource has no accessible canonical relationship view, or it is
                    unavailable in this scope.
                  </p>
                ) : relationships.data?.length ? (
                  <ul className="relationship-list">
                    {relationships.data.map((relationship) => (
                      <li key={relationship.relationshipId}>
                        <strong>{relationship.relationshipType.replaceAll("_", " ")}</strong>
                        <span>
                          {safeShortId(relationship.source.objectId)} →{" "}
                          {safeShortId(relationship.target.objectId)}
                        </span>
                        <small>
                          {relationship.currentState} · graph revision {relationship.graphRevision}{" "}
                          · {relationship.provenance.originType.replaceAll("_", " ")}
                        </small>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>No relationships are visible for this resource.</p>
                )}
              </section>
              {focusedCitation && (
                <section aria-labelledby="citation-inspector-heading">
                  <small>Citation inspector</small>
                  <h2 id="citation-inspector-heading">{focusedCitation.sourceTitle}</h2>
                  <p>{focusedCitation.excerpt}</p>
                  <dl className="universe-facts">
                    <div>
                      <dt>Locator</dt>
                      <dd>{JSON.stringify(focusedCitation.locator)}</dd>
                    </div>
                    <div>
                      <dt>Source version</dt>
                      <dd>{focusedCitation.sourceVersion}</dd>
                    </div>
                    <div>
                      <dt>Excerpt hash</dt>
                      <dd>{safeShortId(focusedCitation.excerptSha256)}</dd>
                    </div>
                  </dl>
                  <a href={getTraceUrl(focusedCitation.traceId)} target="_blank" rel="noreferrer">
                    View citation Trace <ExternalLink size={13} />
                  </a>
                </section>
              )}
              {mergedViewport.bounded && (
                <p className="bounded-warning">
                  <CircleAlert size={14} /> This view is bounded. Unloaded resources remain
                  unselected and do not disappear from authoritative state.
                </p>
              )}
            </>
          )}

          {panel === "workflow" && workflow.data && (
            <>
              <section>
                <small>Execution facts</small>
                <h2>{safeShortId(workflow.data.executionId)}</h2>
                <dl className="universe-facts">
                  <div>
                    <dt>Version</dt>
                    <dd>{safeShortId(workflow.data.versionId)}</dd>
                  </div>
                  <div>
                    <dt>Plan</dt>
                    <dd>{safeShortId(workflow.data.planDigest)}</dd>
                  </div>
                  <div>
                    <dt>Deadline</dt>
                    <dd>{new Date(workflow.data.deadlineAt).toLocaleString()}</dd>
                  </div>
                  <div>
                    <dt>Graph revision</dt>
                    <dd>{workflow.data.graphRevision}</dd>
                  </div>
                </dl>
                <a href={getTraceUrl(workflow.data.traceId)} target="_blank" rel="noreferrer">
                  View workflow Trace <ExternalLink size={13} />
                </a>
              </section>
              {focusedStep ? (
                <section aria-labelledby="step-inspector-heading">
                  <small>Step inspector</small>
                  <h2 id="step-inspector-heading">{focusedStep.stepKey}</h2>
                  <dl className="universe-facts">
                    <div>
                      <dt>Status</dt>
                      <dd>{focusedStep.status.replaceAll("_", " ")}</dd>
                    </div>
                    <div>
                      <dt>Capability</dt>
                      <dd>{focusedStep.capability}</dd>
                    </div>
                    <div>
                      <dt>Risk</dt>
                      <dd>{focusedStep.riskClass.replaceAll("_", " ")}</dd>
                    </div>
                    <div>
                      <dt>Action</dt>
                      <dd>{focusedStep.requestedAction ?? "No mutation requested"}</dd>
                    </div>
                    <div>
                      <dt>Affected resource</dt>
                      <dd>{safeShortId(focusedStep.affectedResourceId)}</dd>
                    </div>
                    <div>
                      <dt>Dependencies</dt>
                      <dd>{focusedStep.dependsOn.join(", ") || "None"}</dd>
                    </div>
                    <div>
                      <dt>Effect</dt>
                      <dd>{safeShortId(focusedStep.effectId)}</dd>
                    </div>
                    <div>
                      <dt>Rollback</dt>
                      <dd>{safeShortId(focusedStep.rollbackResultId)}</dd>
                    </div>
                  </dl>
                  {focusedStep.status === "awaiting_approval" && focusedStep.approvalId && (
                    <div className="approval-actions">
                      <button
                        type="button"
                        onClick={() =>
                          setConfirmation({
                            kind: "approval",
                            step: focusedStep,
                            decision: "denied",
                          })
                        }
                      >
                        Deny
                      </button>
                      <button
                        type="button"
                        className="primary-button"
                        onClick={() =>
                          setConfirmation({
                            kind: "approval",
                            step: focusedStep,
                            decision: "approved",
                          })
                        }
                      >
                        <ShieldCheck size={14} /> Review approval
                      </button>
                    </div>
                  )}
                </section>
              ) : (
                <p>Select a workflow step for exact status, risk, action, and evidence linkage.</p>
              )}
              <p className="bounded-warning">
                Cancellation preserves Trace, audit, events, model calls, and completed evidence.
                Committed effects remain unless predefined compensation succeeds.
              </p>
            </>
          )}

          {panel === "evidence" && (
            <>
              <section aria-labelledby="trace-heading">
                <small>Safe execution evidence</small>
                <h2 id="trace-heading">Trace inspector</h2>
                {retrievalTrace.isPending ? (
                  <Status>Loading safe Trace summary…</Status>
                ) : retrievalTrace.isError ? (
                  <p role="alert">{getErrorMessage(retrievalTrace.error)}</p>
                ) : retrievalTrace.data ? (
                  <>
                    <p>
                      {retrievalTrace.data.eventTypes.length} events · statuses{" "}
                      {[...new Set(retrievalTrace.data.statuses)].join(", ")}
                    </p>
                    <a
                      href={getTraceUrl(retrievalTrace.data.traceId)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open scoped Trace <ExternalLink size={13} />
                    </a>
                    <p className="universe-help">
                      Trace shows auditable provenance and execution evidence, never private model
                      chain of thought.
                    </p>
                  </>
                ) : (
                  <p>No retrieval Trace selected.</p>
                )}
              </section>
              <section aria-labelledby="bundle-heading">
                <small>Authority-filtered export</small>
                <h2 id="bundle-heading">Trace Evidence Bundle</h2>
                {activeBundle ? (
                  <dl className="universe-facts">
                    <div>
                      <dt>Status</dt>
                      <dd>{activeBundle.state.replaceAll("_", " ")}</dd>
                    </div>
                    <div>
                      <dt>Size</dt>
                      <dd>{activeBundle.byteSize.toLocaleString()} bytes</dd>
                    </div>
                    <div>
                      <dt>Artifact hash</dt>
                      <dd>{safeShortId(activeBundle.artifactSha256)}</dd>
                    </div>
                  </dl>
                ) : (
                  <p>No Evidence Bundle exists for the selected retrieval.</p>
                )}
                <div className="bundle-actions">
                  {discoveredRetrievalId && !activeBundle && (
                    <button
                      type="button"
                      disabled={generateBundle.isPending}
                      onClick={() => generateBundle.mutate()}
                    >
                      <Box size={14} /> Generate excerpt bundle
                    </button>
                  )}
                  {activeBundle?.state === "completed" && (
                    <button
                      type="button"
                      disabled={downloadBundle.isPending}
                      onClick={() => downloadBundle.mutate()}
                    >
                      <Download size={14} /> Download authorized ZIP
                    </button>
                  )}
                </div>
                <p className="universe-help">
                  This control does not grant export authority. The server decides which evidence
                  may be packaged and downloaded.
                </p>
              </section>
            </>
          )}

          {panel === "activity" && (
            <section>
              <small>Projection boundary</small>
              <h2>Chronological view</h2>
              <p>
                Activity is a bounded, deduplicated projection of append-only events. It is not the
                source of workflow or authority state.
              </p>
              <button type="button" onClick={() => void activity.refetch()}>
                <RefreshCw size={14} /> Refresh activity
              </button>
            </section>
          )}
        </aside>
      </div>

      {confirmation?.kind === "approval" && (
        <ConfirmationDialog
          title={`${confirmation.decision === "approved" ? "Approve" : "Deny"} ${confirmation.step.stepKey}?`}
          description={
            <>
              <p>
                Workflow {safeShortId(workflow.data?.executionId)} requests{" "}
                <strong>{confirmation.step.requestedAction ?? "workflow approval"}</strong>.
              </p>
              <p>
                Affected resource {safeShortId(confirmation.step.affectedResourceId)} · risk{" "}
                {confirmation.step.riskClass.replaceAll("_", " ")} · deadline{" "}
                {workflow.data
                  ? new Date(workflow.data.deadlineAt).toLocaleString()
                  : "unavailable"}
                .
              </p>
              <p>The server will revalidate scope, policy, approval context, and current state.</p>
            </>
          }
          confirmLabel={confirmation.decision === "approved" ? "Approve once" : "Deny once"}
          destructive={confirmation.decision === "denied"}
          busy={approval.isPending}
          onCancel={() => setConfirmation(null)}
          onConfirm={() =>
            approval.mutate({ step: confirmation.step, decision: confirmation.decision })
          }
        />
      )}
      {confirmation?.kind === "cancel" && (
        <ConfirmationDialog
          title="Request workflow cancellation?"
          description={
            <>
              <p>
                New work will stop at a governed boundary. Completed evidence and historical Trace
                remain.
              </p>
              <p>
                Committed effects may remain. Predefined compensation, when required, has its own
                approval and may fail visibly.
              </p>
            </>
          }
          confirmLabel="Request cancellation"
          destructive
          busy={cancellation.isPending}
          onCancel={() => setConfirmation(null)}
          onConfirm={() => cancellation.mutate()}
        />
      )}
    </main>
  );
}
