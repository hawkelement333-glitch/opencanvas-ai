"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  FlaskConical,
  GitCompare,
  LoaderCircle,
  MessageSquareText,
  PauseCircle,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { type FormEvent, useMemo, useState } from "react";

import { ConfirmationDialog } from "@/components/universe/confirmation-dialog";
import {
  agentStudioApi,
  canvasApi,
  getErrorMessage,
  getTraceUrl,
  workspaceApi,
} from "@/lib/api-client";
import type {
  AgentActivationRequest,
  AgentVersion,
  BoundedAgent,
  CommunicationProfile,
  CommunicationRevision,
} from "@/lib/agent-studio-contracts";

type View = "agents" | "activation" | "invocation" | "proposals" | "communication";
type Confirmation =
  | {
      kind: "activation";
      request: AgentActivationRequest;
      decision: "approved" | "denied";
    }
  | { kind: "proposal"; proposalId: string; decision: "accepted" | "rejected" }
  | { kind: "lifecycle"; operation: "suspend" | "restore" | "retire" }
  | { kind: "revision"; revision: CommunicationRevision; decision: "accepted" | "rejected" }
  | null;

function uniqueKey(prefix: string): string {
  return `${prefix}:${crypto.randomUUID()}`;
}

function short(value: string): string {
  return value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

function label(value: string): string {
  return value.replaceAll("_", " ").replaceAll(".", " · ");
}

function latestVersion(agent: BoundedAgent | null): AgentVersion | null {
  return (
    agent?.versions.toSorted((left, right) => right.versionNumber - left.versionNumber)[0] ?? null
  );
}

function Status({ error, children }: { error?: boolean; children: React.ReactNode }) {
  return (
    <div
      className={`studio-status${error ? " studio-status--error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {error ? <CircleAlert size={16} /> : <LoaderCircle className="spin" size={16} />}
      <span>{children}</span>
    </div>
  );
}

function DefinitionForm({
  registries,
  onSubmit,
  submitLabel,
  busy,
}: {
  registries: {
    agentKinds: string[];
    capabilities: string[];
    resourceKinds: string[];
    riskClasses: string[];
    providers: Record<string, string[]>;
  };
  onSubmit: (input: {
    kind: string;
    displayName: string;
    description: string;
    version: Record<string, unknown>;
  }) => void;
  submitLabel: string;
  busy: boolean;
}) {
  const [kind, setKind] = useState(registries.agentKinds[0] ?? "");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [purpose, setPurpose] = useState("");
  const [instruction, setInstruction] = useState("");
  const [workflowVersionId, setWorkflowVersionId] = useState("");
  const [capability, setCapability] = useState(
    registries.capabilities.includes("context.selected.read")
      ? "context.selected.read"
      : (registries.capabilities[0] ?? ""),
  );
  const [resourceKind, setResourceKind] = useState(
    registries.resourceKinds.includes("canonical_object")
      ? "canonical_object"
      : (registries.resourceKinds[0] ?? ""),
  );
  const [provider, setProvider] = useState(Object.keys(registries.providers)[0] ?? "");
  const models = registries.providers[provider] ?? [];
  const [modelChoice, setModelChoice] = useState("");
  const model = models.includes(modelChoice) ? modelChoice : (models[0] ?? "");
  const [riskClass, setRiskClass] = useState(
    registries.riskClasses.includes("r1_draft") ? "r1_draft" : (registries.riskClasses[0] ?? ""),
  );

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit({
      kind,
      displayName,
      description,
      version: {
        schemaVersion: "bounded-agent-definition-v1",
        purpose,
        systemInstruction: instruction,
        workflowVersionIds: [workflowVersionId],
        capabilityRequirements: [{ capability, resourceKind }],
        selectedContextPolicy: "required_explicit",
        provider,
        model,
        limits: {
          maxWorkflowExecutions: 1,
          maxModelCalls: 4,
          maxRetrievalCalls: 4,
          maxEffects: 1,
          maxApprovals: 2,
          maxRetries: 2,
          maxDurationSeconds: 300,
          maxInputChars: 20_000,
          maxOutputChars: 20_000,
          maxEvidenceBundleRequests: 1,
        },
        communicationPolicy: { profileVersionId: null, requireHumanAcceptance: true },
        evaluationPolicy: "human_review",
        riskClass,
      },
    });
  };

  return (
    <form className="studio-form" onSubmit={submit}>
      <label>
        Agent kind
        <select value={kind} onChange={(event) => setKind(event.target.value)}>
          {registries.agentKinds.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
      </label>
      <label>
        Display name
        <input
          required
          maxLength={160}
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
        />
      </label>
      <label className="studio-form__wide">
        Description
        <textarea
          required
          maxLength={1000}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </label>
      <label className="studio-form__wide">
        Bounded purpose
        <textarea
          required
          maxLength={2000}
          value={purpose}
          onChange={(event) => setPurpose(event.target.value)}
        />
      </label>
      <label className="studio-form__wide">
        System instruction
        <textarea
          required
          maxLength={8000}
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="Define behavior. Authority, approvals, and limits remain server controlled."
        />
      </label>
      <label className="studio-form__wide">
        Active workflow version ID
        <input
          required
          type="text"
          pattern="[0-9a-fA-F-]{36}"
          value={workflowVersionId}
          onChange={(event) => setWorkflowVersionId(event.target.value)}
        />
      </label>
      <label>
        Capability requirement
        <select value={capability} onChange={(event) => setCapability(event.target.value)}>
          {registries.capabilities.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
      </label>
      <label>
        Resource kind
        <select value={resourceKind} onChange={(event) => setResourceKind(event.target.value)}>
          {registries.resourceKinds.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
      </label>
      <label>
        Provider
        <select
          value={provider}
          onChange={(event) => {
            setProvider(event.target.value);
            setModelChoice("");
          }}
        >
          {Object.keys(registries.providers).map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
      </label>
      <label>
        Model
        <select value={model} onChange={(event) => setModelChoice(event.target.value)}>
          {models.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
      </label>
      <label>
        Risk class
        <select value={riskClass} onChange={(event) => setRiskClass(event.target.value)}>
          {registries.riskClasses.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
      </label>
      <div className="studio-form__wide studio-callout">
        <ShieldCheck size={17} />
        <span>
          Creation produces an immutable draft. Validation never activates it or creates authority.
        </span>
      </div>
      <button className="primary-button studio-form__submit" disabled={busy} type="submit">
        {busy ? "Saving immutable draft…" : submitLabel}
      </button>
    </form>
  );
}

export function AgentStudioApp({
  requestedWorkspaceId,
  requestedCanvasId,
  requestedAgentId,
}: {
  requestedWorkspaceId?: string;
  requestedCanvasId?: string;
  requestedAgentId?: string;
}) {
  const queryClient = useQueryClient();
  const [view, setView] = useState<View>("agents");
  const [showCreate, setShowCreate] = useState(false);
  const [showVersionForm, setShowVersionForm] = useState(false);
  const [lifecycleFilter, setLifecycleFilter] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState(requestedAgentId ?? "");
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [queryText, setQueryText] = useState("");
  const [selectedObjectIds, setSelectedObjectIds] = useState("");
  const [evaluationSummary, setEvaluationSummary] = useState("");
  const [evaluationOutcome, setEvaluationOutcome] = useState("meets_requirements");
  const [proposalKind, setProposalKind] = useState("evaluation_recommendation");
  const [proposalPayload, setProposalPayload] = useState(
    '{"summary":"Review this bounded recommendation."}',
  );
  const [profileName, setProfileName] = useState("");
  const [revisionOriginal, setRevisionOriginal] = useState("");
  const [revisionText, setRevisionText] = useState("");
  const [pendingRevision, setPendingRevision] = useState<CommunicationRevision | null>(null);

  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: ({ signal }) => workspaceApi.list(signal),
  });
  const workspaceId = workspaces.data?.some((row) => row.id === requestedWorkspaceId)
    ? (requestedWorkspaceId ?? "")
    : (workspaces.data?.[0]?.id ?? "");
  const canvases = useQuery({
    queryKey: ["canvases", workspaceId],
    queryFn: ({ signal }) => canvasApi.listCanvases(workspaceId, signal),
    enabled: Boolean(workspaceId),
  });
  const canvasId = canvases.data?.some((row) => row.id === requestedCanvasId)
    ? (requestedCanvasId ?? "")
    : (canvases.data?.[0]?.id ?? "");
  const scopeReady = Boolean(workspaceId && canvasId);

  const registries = useQuery({
    queryKey: ["agent-studio-registries", workspaceId, canvasId],
    queryFn: ({ signal }) => agentStudioApi.registries(workspaceId, canvasId, signal),
    enabled: scopeReady,
  });
  const agents = useQuery({
    queryKey: ["agent-studio-agents", workspaceId, canvasId, lifecycleFilter],
    queryFn: ({ signal }) =>
      agentStudioApi.list(workspaceId, canvasId, lifecycleFilter || undefined, signal),
    enabled: scopeReady,
  });
  const profiles = useQuery({
    queryKey: ["agent-studio-profiles", workspaceId, canvasId],
    queryFn: ({ signal }) => agentStudioApi.listProfiles(workspaceId, canvasId, signal),
    enabled: scopeReady,
  });

  const selectedAgent = useMemo(() => {
    const rows = agents.data ?? [];
    return rows.find((agent) => agent.agentId === selectedAgentId) ?? rows[0] ?? null;
  }, [agents.data, selectedAgentId]);
  const selectedVersion = latestVersion(selectedAgent);
  const activeVersion =
    selectedAgent?.versions.find((version) => version.lifecycleState === "active") ?? null;
  const latestInvocation =
    selectedAgent?.invocations.toSorted((left, right) =>
      right.createdAt.localeCompare(left.createdAt),
    )[0] ?? null;
  const pendingActivations =
    selectedAgent?.activationRequests.filter((request) => !request.decision) ?? [];
  const proposals = selectedAgent?.proposals ?? [];

  const refresh = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["agent-studio-agents", workspaceId, canvasId],
    });
    await queryClient.invalidateQueries({
      queryKey: ["agent-studio-profiles", workspaceId, canvasId],
    });
  };

  const create = useMutation({
    mutationFn: (input: Parameters<Parameters<typeof DefinitionForm>[0]["onSubmit"]>[0]) =>
      agentStudioApi.create(workspaceId, canvasId, {
        ...input,
        idempotencyKey: uniqueKey("agent-create"),
      }),
    onSuccess: async (row) => {
      setSelectedAgentId(row.agentId);
      setShowCreate(false);
      setNotice("Immutable agent draft created.");
      await refresh();
    },
  });
  const createVersion = useMutation({
    mutationFn: (input: Parameters<Parameters<typeof DefinitionForm>[0]["onSubmit"]>[0]) =>
      agentStudioApi.createVersion(workspaceId, canvasId, selectedAgent?.agentId ?? "", {
        version: input.version,
        idempotencyKey: uniqueKey("agent-version"),
      }),
    onSuccess: async () => {
      setShowVersionForm(false);
      setNotice("A new immutable version was created; history was preserved.");
      await refresh();
    },
  });
  const validate = useMutation({
    mutationFn: () =>
      agentStudioApi.validate(workspaceId, canvasId, selectedVersion?.versionId ?? ""),
    onSuccess: async (report) => {
      setNotice(`Validation completed: ${label(report.outcome)}.`);
      await refresh();
    },
  });
  const activationRequest = useMutation({
    mutationFn: () =>
      agentStudioApi.requestActivation(
        workspaceId,
        canvasId,
        selectedVersion?.versionId ?? "",
        uniqueKey("activation"),
      ),
    onSuccess: async () => {
      setNotice("Activation requested. A human decision is still required.");
      setView("activation");
      await refresh();
    },
  });
  const invoke = useMutation({
    mutationFn: () => {
      const objectIds = selectedObjectIds
        .split(/[\s,]+/)
        .map((item) => item.trim())
        .filter(Boolean);
      const workflowVersionId = activeVersion?.workflowBindings[0]?.workflowVersionId ?? "";
      return agentStudioApi.invoke(workspaceId, canvasId, selectedAgent?.agentId ?? "", {
        workflowVersionId,
        query: queryText,
        selectedObjectIds: objectIds,
        seedObjectIds: objectIds,
        idempotencyKey: uniqueKey("invocation"),
      });
    },
    onSuccess: async (row) => {
      setNotice(
        `Controlled workflow ${label(row.workflowStatus)}. Invocation ${short(row.invocationId)} recorded.`,
      );
      await refresh();
    },
  });
  const evaluate = useMutation({
    mutationFn: () =>
      agentStudioApi.evaluate(workspaceId, canvasId, latestInvocation?.invocationId ?? "", {
        outcome: evaluationOutcome,
        summary: evaluationSummary,
        recommendations: [],
        idempotencyKey: uniqueKey("evaluation"),
      }),
    onSuccess: async () => {
      setEvaluationSummary("");
      setNotice("Evaluation bound to exact workflow evidence.");
      await refresh();
    },
  });
  const createProposal = useMutation({
    mutationFn: () =>
      agentStudioApi.createProposal(workspaceId, canvasId, {
        kind: proposalKind,
        sourceKind: "human",
        payload: JSON.parse(proposalPayload) as unknown,
        idempotencyKey: uniqueKey("proposal"),
        agentId: selectedAgent?.agentId ?? null,
        sourceInvocationId: latestInvocation?.invocationId ?? null,
      }),
    onSuccess: async () => {
      setNotice("Proposal recorded without activation or increased authority.");
      await refresh();
    },
  });
  const createProfile = useMutation({
    mutationFn: () =>
      agentStudioApi.createProfile(workspaceId, canvasId, {
        name: profileName,
        audience: "general",
        readingLevel: "standard",
        formality: "neutral",
        verbosity: "balanced",
        technicalDepth: "medium",
        orwellRules: false,
        idempotencyKey: uniqueKey("profile"),
      }),
    onSuccess: async () => {
      setProfileName("");
      setNotice("Scoped communication profile created.");
      await refresh();
    },
  });
  const proposeRevision = useMutation({
    mutationFn: () =>
      agentStudioApi.proposeRevision(workspaceId, canvasId, {
        profileVersionId: profiles.data?.[0]?.profileVersionId ?? "",
        sourceInvocationId: latestInvocation?.invocationId ?? null,
        originalText: revisionOriginal,
        revisedText: revisionText,
        citationIds: [],
        idempotencyKey: uniqueKey("revision"),
      }),
    onSuccess: (row) => {
      setPendingRevision(row);
      setNotice(
        row.preservationStatus === "preserved"
          ? "Revision is ready for human review."
          : "Revision failed closed because protected facts changed.",
      );
    },
  });
  const decision = useMutation({
    mutationFn: async (item: Exclude<Confirmation, null>) => {
      if (item.kind === "activation")
        return agentStudioApi.decideActivation(
          workspaceId,
          canvasId,
          item.request.activationRequestId,
          item.decision,
        );
      if (item.kind === "proposal")
        return agentStudioApi.decideProposal(workspaceId, canvasId, item.proposalId, item.decision);
      if (item.kind === "revision")
        return agentStudioApi.decideRevision(
          workspaceId,
          canvasId,
          item.revision.revisionId,
          item.decision,
        );
      return agentStudioApi.lifecycle(
        workspaceId,
        canvasId,
        selectedAgent?.agentId ?? "",
        item.operation,
      );
    },
    onSuccess: async () => {
      setConfirmation(null);
      setNotice("Human decision recorded with scoped provenance.");
      await refresh();
    },
  });

  const errors = [
    create.error,
    createVersion.error,
    validate.error,
    activationRequest.error,
    invoke.error,
    evaluate.error,
    createProposal.error,
    createProfile.error,
    proposeRevision.error,
    decision.error,
  ].filter(Boolean);

  return (
    <main className="studio-route">
      <header className="studio-header">
        <div>
          <small>Milestone 5.6 · human governed</small>
          <h1>Bounded Agent Studio</h1>
          <p>Design, validate, activate, invoke, and improve agents without creating authority.</p>
        </div>
        <div className="studio-header__actions">
          <Link
            href={scopeReady ? `/universe?workspaceId=${workspaceId}&canvasId=${canvasId}` : "/"}
          >
            <ArrowLeft size={15} /> Universe
          </Link>
          <button type="button" onClick={() => void refresh()}>
            <RefreshCw size={15} /> Refresh
          </button>
        </div>
      </header>

      <section className="studio-scope" aria-label="Server-derived scope">
        <ShieldCheck size={17} />
        <div>
          <strong>Server-derived authority scope</strong>
          <span>
            User session · workspace {short(workspaceId || "loading")} · canvas{" "}
            {short(canvasId || "loading")}
          </span>
        </div>
        <small>Visual proximity and future sharing never grant authority.</small>
      </section>

      <nav className="studio-tabs" aria-label="Agent Studio sections">
        {(
          [
            ["agents", Bot, "Agents"],
            ["activation", ShieldCheck, "Activation"],
            ["invocation", Play, "Run & evaluate"],
            ["proposals", Sparkles, "Proposals"],
            ["communication", MessageSquareText, "Communication"],
          ] as const
        ).map(([id, Icon, text]) => (
          <button
            key={id}
            type="button"
            aria-current={view === id ? "page" : undefined}
            onClick={() => setView(id)}
          >
            <Icon size={15} /> {text}
          </button>
        ))}
      </nav>

      {notice && (
        <div className="studio-notice" role="status">
          <CheckCircle2 size={16} />
          {notice}
          <button type="button" aria-label="Dismiss notice" onClick={() => setNotice(null)}>
            ×
          </button>
        </div>
      )}
      {errors[0] && <Status error>{getErrorMessage(errors[0])}</Status>}
      {(workspaces.isPending || canvases.isPending || registries.isPending || agents.isPending) && (
        <Status>Loading exact scoped Agent Studio state…</Status>
      )}
      {(workspaces.isError || canvases.isError || registries.isError || agents.isError) && (
        <Status error>Agent Studio state is unavailable in this scope.</Status>
      )}

      {view === "agents" && registries.data && (
        <div className="studio-layout">
          <aside className="studio-list">
            <div className="studio-panel-heading">
              <div>
                <small>Scoped identities</small>
                <h2>Agents</h2>
              </div>
              <button type="button" onClick={() => setShowCreate((value) => !value)}>
                <Plus size={15} /> New
              </button>
            </div>
            <label>
              Lifecycle filter
              <select
                value={lifecycleFilter}
                onChange={(event) => setLifecycleFilter(event.target.value)}
              >
                <option value="">All states</option>
                {registries.data.agentLifecycles.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <ul>
              {(agents.data ?? []).map((agent) => (
                <li key={agent.agentId}>
                  <button
                    type="button"
                    aria-current={selectedAgent?.agentId === agent.agentId}
                    onClick={() => setSelectedAgentId(agent.agentId)}
                  >
                    <Bot size={18} />
                    <span>
                      <strong>{agent.displayName}</strong>
                      <small>
                        {label(agent.lifecycleState)} · {agent.versions.length} version
                        {agent.versions.length === 1 ? "" : "s"}
                      </small>
                    </span>
                    <ChevronRight size={15} />
                  </button>
                </li>
              ))}
            </ul>
          </aside>
          <section className="studio-main">
            {showCreate ? (
              <>
                <div className="studio-panel-heading">
                  <div>
                    <small>New bounded identity</small>
                    <h2>Draft agent definition</h2>
                  </div>
                </div>
                <DefinitionForm
                  registries={registries.data}
                  busy={create.isPending}
                  submitLabel="Create draft agent"
                  onSubmit={(input) => create.mutate(input)}
                />
              </>
            ) : selectedAgent ? (
              <>
                <div className="studio-panel-heading">
                  <div>
                    <small>{label(selectedAgent.kind)}</small>
                    <h2>{selectedAgent.displayName}</h2>
                    <p>{selectedAgent.description}</p>
                  </div>
                  <span className={`studio-pill studio-pill--${selectedAgent.lifecycleState}`}>
                    {label(selectedAgent.lifecycleState)}
                  </span>
                </div>
                <div className="studio-actions">
                  <button type="button" onClick={() => setShowVersionForm((value) => !value)}>
                    <GitCompare size={15} /> New version
                  </button>
                  <button
                    type="button"
                    disabled={!selectedVersion || validate.isPending}
                    onClick={() => validate.mutate()}
                  >
                    <FlaskConical size={15} /> Validate latest
                  </button>
                  <button
                    type="button"
                    disabled={!selectedVersion || activationRequest.isPending}
                    onClick={() => activationRequest.mutate()}
                  >
                    <ShieldCheck size={15} /> Request activation
                  </button>
                  {selectedAgent.lifecycleState === "active" && (
                    <button
                      type="button"
                      onClick={() => setConfirmation({ kind: "lifecycle", operation: "suspend" })}
                    >
                      <PauseCircle size={15} /> Suspend
                    </button>
                  )}
                  {selectedAgent.lifecycleState === "suspended" && (
                    <button
                      type="button"
                      onClick={() => setConfirmation({ kind: "lifecycle", operation: "restore" })}
                    >
                      <Play size={15} /> Restore
                    </button>
                  )}
                  {selectedAgent.lifecycleState !== "retired" && (
                    <button
                      className="danger-button"
                      type="button"
                      onClick={() => setConfirmation({ kind: "lifecycle", operation: "retire" })}
                    >
                      <XCircle size={15} /> Retire
                    </button>
                  )}
                </div>
                {showVersionForm && (
                  <div className="studio-subpanel">
                    <h3>Create a new immutable version</h3>
                    <p>
                      The prior version stays intact. Private instructions are never returned by the
                      API, so provide the complete revised definition.
                    </p>
                    <DefinitionForm
                      registries={registries.data}
                      busy={createVersion.isPending}
                      submitLabel="Create immutable version"
                      onSubmit={(input) => createVersion.mutate(input)}
                    />
                  </div>
                )}
                <section className="studio-version-history">
                  <div className="studio-panel-heading">
                    <div>
                      <small>Append-only</small>
                      <h3>Version history</h3>
                    </div>
                    <span>{selectedAgent.versions.length}</span>
                  </div>
                  {selectedAgent.versions
                    .toSorted((left, right) => right.versionNumber - left.versionNumber)
                    .map((version) => (
                      <article key={version.versionId}>
                        <div>
                          <strong>Version {version.versionNumber}</strong>
                          <span className={`studio-pill studio-pill--${version.lifecycleState}`}>
                            {label(version.lifecycleState)}
                          </span>
                        </div>
                        <p>{version.purpose}</p>
                        <dl>
                          <div>
                            <dt>Provider</dt>
                            <dd>
                              {version.provider} / {version.model}
                            </dd>
                          </div>
                          <div>
                            <dt>Workflow</dt>
                            <dd>
                              {version.workflowBindings
                                .map((row) => short(row.workflowVersionId))
                                .join(", ")}
                            </dd>
                          </div>
                          <div>
                            <dt>Digest</dt>
                            <dd>{short(version.contentDigest)}</dd>
                          </div>
                          <div>
                            <dt>Trace</dt>
                            <dd>
                              <a
                                href={getTraceUrl(version.traceId)}
                                target="_blank"
                                rel="noreferrer"
                              >
                                {short(version.traceId)}
                              </a>
                            </dd>
                          </div>
                        </dl>
                      </article>
                    ))}
                </section>
              </>
            ) : (
              <div className="studio-empty">
                <Bot size={30} />
                <h2>No bounded agents</h2>
                <p>
                  Create an immutable draft to begin. It cannot run until validation and human
                  activation succeed.
                </p>
              </div>
            )}
          </section>
        </div>
      )}

      {view === "activation" && (
        <section className="studio-single">
          <div className="studio-panel-heading">
            <div>
              <small>Human approval boundary</small>
              <h2>Activation review</h2>
            </div>
            <span>{pendingActivations.length} pending</span>
          </div>
          <p className="studio-help">
            Validation is evidence, not authority. Review the exact version, workflow digest,
            provider, capabilities, limits, expiry, and scope before deciding.
          </p>
          {pendingActivations.length ? (
            pendingActivations.map((request) => (
              <article className="studio-review" key={request.activationRequestId}>
                <div>
                  <strong>
                    Version{" "}
                    {selectedAgent?.versions.find(
                      (version) => version.versionId === request.agentVersionId,
                    )?.versionNumber ?? "?"}
                  </strong>
                  <small>Expires {new Date(request.expiresAt).toLocaleString()}</small>
                </div>
                <pre>{JSON.stringify(request.authoritySummary, null, 2)}</pre>
                <div className="studio-actions">
                  <button
                    type="button"
                    onClick={() =>
                      setConfirmation({ kind: "activation", request, decision: "denied" })
                    }
                  >
                    Deny
                  </button>
                  <button
                    className="primary-button"
                    type="button"
                    onClick={() =>
                      setConfirmation({ kind: "activation", request, decision: "approved" })
                    }
                  >
                    Approve exact activation
                  </button>
                </div>
              </article>
            ))
          ) : (
            <div className="studio-empty">
              <ShieldCheck size={30} />
              <h3>No pending activation request</h3>
              <p>Validate a draft and request activation from the Agents section.</p>
            </div>
          )}
        </section>
      )}

      {view === "invocation" && (
        <section className="studio-single">
          <div className="studio-panel-heading">
            <div>
              <small>Existing Milestone 5.4 executor</small>
              <h2>Run and evaluate</h2>
            </div>
            {activeVersion && (
              <span className="studio-pill studio-pill--active">
                active v{activeVersion.versionNumber}
              </span>
            )}
          </div>
          <p className="studio-help">
            The active immutable version selects an approved workflow. Explicit context IDs are
            required; the server rechecks scope, bindings, approval, and limits at invocation time.
          </p>
          <form
            className="studio-form"
            onSubmit={(event) => {
              event.preventDefault();
              invoke.mutate();
            }}
          >
            <label className="studio-form__wide">
              Grounded question
              <textarea
                required
                maxLength={4000}
                value={queryText}
                onChange={(event) => setQueryText(event.target.value)}
              />
            </label>
            <label className="studio-form__wide">
              Selected canonical object IDs
              <textarea
                required
                placeholder="UUIDs separated by commas or spaces"
                value={selectedObjectIds}
                onChange={(event) => setSelectedObjectIds(event.target.value)}
              />
            </label>
            <button
              className="primary-button studio-form__submit"
              disabled={!activeVersion || invoke.isPending}
              type="submit"
            >
              {invoke.isPending ? "Starting controlled workflow…" : "Invoke active agent"}
            </button>
          </form>
          {latestInvocation && (
            <div className="studio-subpanel">
              <h3>Latest invocation</h3>
              <dl className="studio-facts">
                <div>
                  <dt>Status</dt>
                  <dd>{label(latestInvocation.workflowStatus)}</dd>
                </div>
                <div>
                  <dt>Workflow execution</dt>
                  <dd>
                    <Link
                      href={`/universe?workspaceId=${workspaceId}&canvasId=${canvasId}&workflowExecutionId=${latestInvocation.workflowExecutionId}`}
                    >
                      {short(latestInvocation.workflowExecutionId)}
                    </Link>
                  </dd>
                </div>
                <div>
                  <dt>Graph revision</dt>
                  <dd>{latestInvocation.graphRevision}</dd>
                </div>
                <div>
                  <dt>Trace</dt>
                  <dd>
                    <a
                      href={getTraceUrl(latestInvocation.traceId)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {short(latestInvocation.traceId)}
                    </a>
                  </dd>
                </div>
              </dl>
              <form
                className="studio-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  evaluate.mutate();
                }}
              >
                <label>
                  Outcome
                  <select
                    value={evaluationOutcome}
                    onChange={(event) => setEvaluationOutcome(event.target.value)}
                  >
                    {(registries.data?.evaluationOutcomes ?? []).map((item) => (
                      <option key={item}>{item}</option>
                    ))}
                  </select>
                </label>
                <label className="studio-form__wide">
                  Evidence-based evaluation
                  <textarea
                    required
                    value={evaluationSummary}
                    onChange={(event) => setEvaluationSummary(event.target.value)}
                  />
                </label>
                <button type="submit" disabled={evaluate.isPending}>
                  Record immutable evaluation
                </button>
              </form>
            </div>
          )}
        </section>
      )}

      {view === "proposals" && (
        <section className="studio-single">
          <div className="studio-panel-heading">
            <div>
              <small>Propose, never self-authorize</small>
              <h2>Adaptive proposals</h2>
            </div>
          </div>
          <p className="studio-help">
            Adaptive Agent Architect proposals may use approved frameworks, data structures, and
            workflows. They cannot activate agents, grant authority, assign private data, install
            tools, or increase limits.
          </p>
          <form
            className="studio-form"
            onSubmit={(event) => {
              event.preventDefault();
              createProposal.mutate();
            }}
          >
            <label>
              Proposal kind
              <select
                value={proposalKind}
                onChange={(event) => setProposalKind(event.target.value)}
              >
                {(registries.data?.proposalKinds ?? []).map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label className="studio-form__wide">
              Structured proposal payload
              <textarea
                required
                value={proposalPayload}
                onChange={(event) => setProposalPayload(event.target.value)}
              />
            </label>
            <button type="submit" disabled={createProposal.isPending}>
              Record proposal
            </button>
          </form>
          <div className="studio-card-grid">
            {proposals.map((proposal) => (
              <article className="studio-review" key={proposal.proposalId}>
                <strong>{label(proposal.kind)}</strong>
                <small>
                  {label(proposal.sourceKind)} · {new Date(proposal.createdAt).toLocaleString()}
                </small>
                <pre>{JSON.stringify(proposal.payload, null, 2)}</pre>
                {proposal.decision ? (
                  <span className={`studio-pill studio-pill--${proposal.decision}`}>
                    {proposal.decision}
                  </span>
                ) : (
                  <div className="studio-actions">
                    <button
                      type="button"
                      onClick={() =>
                        setConfirmation({
                          kind: "proposal",
                          proposalId: proposal.proposalId,
                          decision: "rejected",
                        })
                      }
                    >
                      Reject
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setConfirmation({
                          kind: "proposal",
                          proposalId: proposal.proposalId,
                          decision: "accepted",
                        })
                      }
                    >
                      Accept as draft only
                    </button>
                  </div>
                )}
              </article>
            ))}
          </div>
        </section>
      )}

      {view === "communication" && (
        <section className="studio-single">
          <div className="studio-panel-heading">
            <div>
              <small>Facts and citations protected</small>
              <h2>Communication profiles</h2>
            </div>
            <span>{profiles.data?.length ?? 0}</span>
          </div>
          <form
            className="studio-inline-form"
            onSubmit={(event) => {
              event.preventDefault();
              createProfile.mutate();
            }}
          >
            <label>
              Profile name
              <input
                required
                value={profileName}
                onChange={(event) => setProfileName(event.target.value)}
              />
            </label>
            <button type="submit" disabled={createProfile.isPending}>
              Create scoped profile
            </button>
          </form>
          <ul className="studio-profile-list">
            {(profiles.data ?? []).map((profile: CommunicationProfile) => (
              <li key={profile.profileVersionId}>
                <MessageSquareText size={17} />
                <span>
                  <strong>
                    {profile.name} · v{profile.versionNumber}
                  </strong>
                  <small>
                    {profile.audience} · {profile.formality} · {profile.verbosity} · canvas{" "}
                    {short(profile.canvasId)}
                  </small>
                </span>
              </li>
            ))}
          </ul>
          {profiles.data?.length ? (
            <div className="studio-subpanel">
              <h3>Propose an English revision</h3>
              <p>
                Numbers, dates, measurements, URLs, hashes, names, quotes, citations, conflicts,
                bounded-result warnings, effects, and cancellation language are preserved.
                Acceptance is always human.
              </p>
              <form
                className="studio-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  proposeRevision.mutate();
                }}
              >
                <label className="studio-form__wide">
                  Original text
                  <textarea
                    required
                    value={revisionOriginal}
                    onChange={(event) => setRevisionOriginal(event.target.value)}
                  />
                </label>
                <label className="studio-form__wide">
                  Proposed revision
                  <textarea
                    required
                    value={revisionText}
                    onChange={(event) => setRevisionText(event.target.value)}
                  />
                </label>
                <button type="submit" disabled={proposeRevision.isPending}>
                  Check protected facts
                </button>
              </form>
              {pendingRevision && (
                <article className="studio-comparison">
                  <div>
                    <small>Original</small>
                    <p>{pendingRevision.originalText}</p>
                  </div>
                  <div>
                    <small>Revision · {label(pendingRevision.preservationStatus)}</small>
                    <p>{pendingRevision.revisedText}</p>
                  </div>
                  <div className="studio-actions">
                    <button
                      type="button"
                      onClick={() =>
                        setConfirmation({
                          kind: "revision",
                          revision: pendingRevision,
                          decision: "rejected",
                        })
                      }
                    >
                      Reject
                    </button>
                    <button
                      className="primary-button"
                      type="button"
                      disabled={pendingRevision.preservationStatus !== "preserved"}
                      onClick={() =>
                        setConfirmation({
                          kind: "revision",
                          revision: pendingRevision,
                          decision: "accepted",
                        })
                      }
                    >
                      Accept safe revision
                    </button>
                  </div>
                </article>
              )}
            </div>
          ) : null}
        </section>
      )}

      {confirmation && (
        <ConfirmationDialog
          title={
            confirmation.kind === "activation"
              ? `${confirmation.decision === "approved" ? "Approve" : "Deny"} exact activation?`
              : confirmation.kind === "lifecycle"
                ? `${label(confirmation.operation)} this agent?`
                : confirmation.kind === "proposal"
                  ? `${label(confirmation.decision)} this proposal?`
                  : `${label(confirmation.decision)} this revision?`
          }
          description={
            <>
              <p>
                This records an immutable human decision in the exact user, workspace, and canvas
                scope.
              </p>
              {confirmation.kind === "activation" && (
                <p>
                  Approval applies only to version {short(confirmation.request.agentVersionId)} and
                  expires with this request.
                </p>
              )}
            </>
          }
          confirmLabel="Record decision"
          destructive={
            (confirmation.kind === "activation" && confirmation.decision === "denied") ||
            (confirmation.kind === "lifecycle" && confirmation.operation !== "restore") ||
            (confirmation.kind !== "activation" &&
              confirmation.kind !== "lifecycle" &&
              confirmation.decision === "rejected")
          }
          busy={decision.isPending}
          onCancel={() => setConfirmation(null)}
          onConfirm={() => decision.mutate(confirmation)}
        />
      )}
    </main>
  );
}
