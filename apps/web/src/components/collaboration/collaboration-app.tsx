"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { APIError, accountApi, canvasApi, collaborationApi, workspaceApi } from "@/lib/api-client";
import {
  collaborationKeys,
  type CollaborationContext,
  type CollaborationPermission,
  type ResourceKind,
} from "@/lib/collaboration-contracts";

const TABS = ["Overview", "People", "Access", "Discussions", "Automations"] as const;
const ROLES = ["administrator", "editor", "approver", "member", "viewer"] as const;
const RESOURCE_KINDS = ["canvas", "canonical_object", "workflow", "agent"] as const;
const CAPABILITIES = [
  "workspace.metadata.read",
  "canvas.snapshot.read",
  "context.selected.read",
  "document.version.read",
  "trace.scoped.read",
  "retrieval.selected.search",
  "draft.note.create",
  "draft.answer.create",
  "canvas.note.create",
  "canvas.note.update",
  "canvas.note.create.rollback",
  "canvas.note.update.rollback",
  "knowledge_graph.relationship.write",
  "workflow.step.execute",
  "evidence.bundle.create",
  "execution.cancel",
] as const;

type Tab = (typeof TABS)[number];

function idempotencyKey(prefix: string): string {
  return `${prefix}.${Date.now()}.${crypto.randomUUID()}`;
}

function shortId(value: string | null | undefined): string {
  return value ? `${value.slice(0, 8)}…${value.slice(-4)}` : "Not assigned";
}

function dateTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function userMessage(error: unknown): string {
  if (!(error instanceof APIError)) return "The operation could not be completed.";
  if (error.status === 404) return "This item is unavailable or you no longer have access.";
  if (error.status === 409) return "The item changed. Refresh and review it before trying again.";
  if (error.status === 410) return "This invitation or transfer has expired.";
  if (error.status === 429) return "The action limit was reached. Wait briefly and try again.";
  if (error.code === "invalid_response") return "The server response was not safe to display.";
  if (error.code === "request_aborted") return "The request was cancelled because context changed.";
  return error.message;
}

function splitIds(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function Status({ children }: { children: React.ReactNode }) {
  return <span className="collaboration-status">{children}</span>;
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="collaboration-empty">{children}</p>;
}

function ErrorState({ error }: { error: unknown }) {
  return (
    <div className="collaboration-error" role="alert">
      <strong>Could not load this section.</strong>
      <span>{userMessage(error)}</span>
    </div>
  );
}

export function CollaborationApp({ initialWorkspaceId }: { initialWorkspaceId?: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [workspaceId, setWorkspaceId] = useState(initialWorkspaceId ?? "");
  const [tab, setTab] = useState<Tab>("Overview");
  const [announcement, setAnnouncement] = useState("");
  const [lastTraceId, setLastTraceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [resourceKind, setResourceKind] = useState<ResourceKind>("canvas");
  const [resourceId, setResourceId] = useState("");
  const [canvasId, setCanvasId] = useState("");

  const user = useQuery({
    queryKey: ["current-user"],
    queryFn: ({ signal }) => accountApi.me(signal),
  });
  const workspaces = useQuery({
    queryKey: ["workspaces", user.data?.id],
    queryFn: ({ signal }) => workspaceApi.list(signal),
    enabled: Boolean(user.data),
  });
  const context = useQuery({
    queryKey:
      user.data && workspaceId
        ? collaborationKeys.context(user.data.id, workspaceId)
        : ["collaboration-context", "disabled"],
    queryFn: ({ signal }) => collaborationApi.context(workspaceId, signal),
    enabled: Boolean(user.data && workspaceId),
    retry: false,
  });

  useEffect(() => {
    if (!workspaceId && workspaces.data?.length) {
      const next = workspaces.data[0]!.id;
      router.replace(`/collaboration?workspaceId=${encodeURIComponent(next)}`);
      const timer = window.setTimeout(() => setWorkspaceId(next), 0);
      return () => window.clearTimeout(timer);
    }
  }, [router, workspaceId, workspaces.data]);

  useEffect(() => {
    if (!(context.error instanceof APIError) || context.error.status !== 404 || !workspaceId)
      return;
    void queryClient.cancelQueries({
      predicate: (query) => query.queryKey.includes(workspaceId),
    });
    queryClient.removeQueries({
      predicate: (query) => query.queryKey.includes(workspaceId),
    });
    const timer = window.setTimeout(() => {
      setResourceId("");
      setCanvasId("");
      setAnnouncement("Workspace access was revoked. Workspace data was cleared.");
    }, 0);
    return () => window.clearTimeout(timer);
  }, [context.error, queryClient, workspaceId]);

  const permissions = useMemo(
    () => new Set(context.data?.permissionCeiling ?? []),
    [context.data?.permissionCeiling],
  );
  const has = (permission: CollaborationPermission) => permissions.has(permission);

  async function switchWorkspace(next: string) {
    if (next === workspaceId) return;
    const previous = workspaceId;
    if (previous) {
      await queryClient.cancelQueries({
        predicate: (query) => query.queryKey.includes(previous),
      });
      queryClient.removeQueries({
        predicate: (query) => query.queryKey.includes(previous),
      });
    }
    setResourceId("");
    setCanvasId("");
    setTab("Overview");
    setLastTraceId("");
    setWorkspaceId(next);
    router.replace(`/collaboration?workspaceId=${encodeURIComponent(next)}`);
    setAnnouncement("Workspace changed. Server authority is being confirmed.");
  }

  async function runAction(
    success: string,
    action: () => Promise<unknown>,
    options: { confirm?: string; authority?: boolean } = {},
  ) {
    if (options.confirm && !window.confirm(options.confirm)) return;
    setBusy(true);
    setAnnouncement("");
    setLastTraceId("");
    try {
      const result = await action();
      const boundedResult = result as {
        duplicate?: boolean;
        status?: string;
        workflowStatus?: string;
        traceId?: string;
      };
      if (user.data && workspaceId) {
        await queryClient.cancelQueries({
          queryKey: ["collaboration", user.data.id, workspaceId],
        });
        queryClient.removeQueries({
          queryKey: ["collaboration", user.data.id, workspaceId],
        });
        await queryClient.invalidateQueries({
          queryKey: collaborationKeys.context(user.data.id, workspaceId),
        });
        await queryClient.invalidateQueries({ queryKey: ["workspaces", user.data.id] });
        await queryClient.invalidateQueries({ queryKey: ["canvases", workspaceId] });
      }
      setAnnouncement(
        `${success}${boundedResult.duplicate ? " (already completed)" : ""}${
          boundedResult.status || boundedResult.workflowStatus
            ? ` Status: ${boundedResult.status ?? boundedResult.workflowStatus}.`
            : ""
        }`,
      );
      setLastTraceId(boundedResult.traceId ?? "");
    } catch (error) {
      setAnnouncement(userMessage(error));
    } finally {
      setBusy(false);
    }
  }

  if (user.isLoading || workspaces.isLoading) {
    return (
      <main className="collaboration-route collaboration-centered">Loading collaboration…</main>
    );
  }
  if (user.isError || workspaces.isError) {
    return (
      <main className="collaboration-route collaboration-centered">
        <ErrorState error={user.error ?? workspaces.error} />
      </main>
    );
  }
  if (!workspaces.data?.length) {
    return (
      <main className="collaboration-route collaboration-centered">
        <section className="collaboration-panel">
          <p className="eyebrow">Multi-workspace collaboration</p>
          <h1>No authorized workspaces</h1>
          <p>You do not currently have an active workspace membership.</p>
          <Link href="/">Return to canvas</Link>
        </section>
      </main>
    );
  }

  return (
    <main className="collaboration-route">
      <header className="collaboration-header">
        <div>
          <p className="eyebrow">SolarPlexus Mobius</p>
          <h1>Collaboration</h1>
          <p>Visibility, authority, ownership, approval, and invocation remain separate.</p>
        </div>
        <nav aria-label="Product areas">
          <Link href="/">Canvas</Link>
          <Link href="/universe">Universe</Link>
          <Link href="/agents">Agent Studio</Link>
        </nav>
      </header>

      <section className="collaboration-switcher" aria-labelledby="workspace-switcher-title">
        <div>
          <h2 id="workspace-switcher-title">Current workspace</h2>
          <p>Changing workspace clears scoped browser state and reconfirms server authority.</p>
        </div>
        <label>
          Authorized workspace
          <select
            value={workspaceId}
            onChange={(event) => void switchWorkspace(event.target.value)}
            disabled={busy}
          >
            {workspaces.data.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
              </option>
            ))}
          </select>
        </label>
      </section>

      <div className="collaboration-live" aria-live="polite" aria-atomic="true">
        {announcement}
        {lastTraceId && (
          <>
            {" "}
            <Link href={`/universe?traceId=${lastTraceId}`}>Open Trace</Link>
          </>
        )}
      </div>

      {context.isLoading && (
        <section className="collaboration-panel">Confirming authority…</section>
      )}
      {context.isError && (
        <section className="collaboration-panel">
          <ErrorState error={context.error} />
          <button onClick={() => void context.refetch()}>Retry authority check</button>
        </section>
      )}
      {context.data && (
        <>
          <ContextStrip context={context.data} userEmail={user.data?.email ?? ""} />
          <nav className="collaboration-tabs" role="tablist" aria-label="Collaboration areas">
            {TABS.map((item, index) => (
              <button
                key={item}
                id={`collaboration-tab-${index}`}
                role="tab"
                aria-selected={tab === item}
                aria-controls="collaboration-tab-panel"
                tabIndex={tab === item ? 0 : -1}
                onClick={() => setTab(item)}
                onKeyDown={(event) => {
                  const nextIndex =
                    event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? TABS.length - 1
                        : event.key === "ArrowRight"
                          ? (index + 1) % TABS.length
                          : event.key === "ArrowLeft"
                            ? (index - 1 + TABS.length) % TABS.length
                            : -1;
                  if (nextIndex < 0) return;
                  event.preventDefault();
                  setTab(TABS[nextIndex]!);
                  document.getElementById(`collaboration-tab-${nextIndex}`)?.focus();
                }}
              >
                {item}
              </button>
            ))}
          </nav>
          <section
            id="collaboration-tab-panel"
            className="collaboration-content"
            role="tabpanel"
            aria-labelledby={`collaboration-tab-${TABS.indexOf(tab)}`}
            tabIndex={0}
          >
            {tab === "Overview" && <Overview context={context.data} />}
            {tab === "People" && (
              <People context={context.data} has={has} busy={busy} runAction={runAction} />
            )}
            {tab === "Access" && (
              <Access
                context={context.data}
                has={has}
                busy={busy}
                resourceKind={resourceKind}
                resourceId={resourceId}
                setResourceKind={setResourceKind}
                setResourceId={setResourceId}
                runAction={runAction}
              />
            )}
            {tab === "Discussions" && (
              <Discussions
                context={context.data}
                has={has}
                busy={busy}
                resourceKind={resourceKind}
                resourceId={resourceId}
                setResourceKind={setResourceKind}
                setResourceId={setResourceId}
                runAction={runAction}
              />
            )}
            {tab === "Automations" && (
              <Automations
                context={context.data}
                busy={busy}
                canvasId={canvasId}
                setCanvasId={setCanvasId}
                runAction={runAction}
              />
            )}
          </section>
        </>
      )}
    </main>
  );
}

function ContextStrip({
  context,
  userEmail,
}: {
  context: CollaborationContext;
  userEmail: string;
}) {
  return (
    <section className="collaboration-context" aria-label="Confirmed workspace authority">
      <div>
        <span>Workspace</span>
        <strong>{context.workspaceName}</strong>
        <small>{context.workspaceLifecycleState}</small>
      </div>
      <div>
        <span>Signed in</span>
        <strong>{userEmail}</strong>
        <small>User {shortId(context.authenticatedUserId)}</small>
      </div>
      <div>
        <span>Membership</span>
        <strong>{context.role}</strong>
        <small>{context.membershipState}</small>
      </div>
      <div>
        <span>Authority state</span>
        <strong>Generation {context.authorityGeneration}</strong>
        <small>Server confirmed</small>
      </div>
    </section>
  );
}

function Overview({ context }: { context: CollaborationContext }) {
  const summaries: Record<string, string> = {
    owner:
      "Owns the workspace and may request ownership transfer. Resource authority is still typed.",
    administrator:
      "May administer approved collaboration features. Ownership and controlled-agent authority stay separate.",
    editor:
      "May contribute to approved resources. Visibility and invocation remain separate decisions.",
    approver:
      "May review only when a bounded approval-authority record and Milestone 4 policy also allow it.",
    member:
      "May participate in approved resources and invoke only when the server separately permits it.",
    viewer: "May inspect visible resources. Viewing does not grant contribution or invocation.",
  };
  return (
    <div className="collaboration-grid">
      <article className="collaboration-panel">
        <p className="eyebrow">Your role</p>
        <h2>{context.role}</h2>
        <p>{summaries[context.role]}</p>
      </article>
      <article className="collaboration-panel">
        <p className="eyebrow">Workspace ownership</p>
        <h2>{shortId(context.workspaceOwnerUserId)}</h2>
        <p>
          Creator identity, workspace ownership, membership, role, and action authority are
          distinct.
        </p>
      </article>
      <article className="collaboration-panel collaboration-panel--wide">
        <p className="eyebrow">Server-returned permission ceiling</p>
        <h2>{context.permissionCeiling.length} bounded operations</h2>
        <ul className="collaboration-chip-list" aria-label="Current permission ceiling">
          {context.permissionCeiling.map((permission) => (
            <li key={permission}>{permission.replaceAll(".", " ")}</li>
          ))}
        </ul>
        <p className="collaboration-note">
          This is an operation ceiling, not proof of authority over a particular resource. Every
          action is checked again by the server.
        </p>
      </article>
    </div>
  );
}

type ActionRunner = (
  success: string,
  action: () => Promise<unknown>,
  options?: { confirm?: string; authority?: boolean },
) => Promise<void>;

function People({
  context,
  has,
  busy,
  runAction,
}: {
  context: CollaborationContext;
  has: (permission: CollaborationPermission) => boolean;
  busy: boolean;
  runAction: ActionRunner;
}) {
  const scope = collaborationKeys.scoped(
    context.authenticatedUserId,
    context.workspaceId,
    context.authorityGeneration,
  );
  const members = useQuery({
    queryKey: [...scope, "memberships"],
    queryFn: ({ signal }) => collaborationApi.memberships(context.workspaceId, signal),
    enabled: has("membership.view"),
  });
  const invitations = useQuery({
    queryKey: [...scope, "invitations"],
    queryFn: ({ signal }) => collaborationApi.invitations(context.workspaceId, signal),
    enabled: has("membership.view"),
  });
  const approvals = useQuery({
    queryKey: [...scope, "approval-authority"],
    queryFn: ({ signal }) => collaborationApi.approvalAuthorities(context.workspaceId, signal),
    enabled: has("role.assign"),
  });
  const [email, setEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<(typeof ROLES)[number]>("member");
  const [inviteId, setInviteId] = useState("");
  const [inviteToken, setInviteToken] = useState("");
  const [approvalMember, setApprovalMember] = useState("");
  const [capability, setCapability] = useState<(typeof CAPABILITIES)[number]>(CAPABILITIES[0]);
  const [approvalResource, setApprovalResource] = useState("");

  if (!has("membership.view")) {
    return <Empty>Member administration is not available to your current membership.</Empty>;
  }
  if (members.isError || invitations.isError || approvals.isError) {
    return <ErrorState error={members.error ?? invitations.error ?? approvals.error} />;
  }
  return (
    <div className="collaboration-stack">
      <section className="collaboration-panel">
        <div className="collaboration-section-heading">
          <div>
            <p className="eyebrow">Memberships</p>
            <h2>People and roles</h2>
          </div>
          <Status>{members.data?.length ?? 0} visible members</Status>
        </div>
        {!members.data?.length ? (
          <Empty>No memberships are available.</Empty>
        ) : (
          <div className="collaboration-table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Member</th>
                  <th scope="col">Role</th>
                  <th scope="col">State</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {members.data.map((member) => {
                  const isSelf = member.membershipId === context.membershipId;
                  const protectedOwner = member.role === "owner";
                  return (
                    <tr key={member.membershipId}>
                      <td>
                        {shortId(member.userId)}
                        {isSelf && <small> You</small>}
                      </td>
                      <td>
                        {has("role.assign") && !protectedOwner && !isSelf ? (
                          <select
                            aria-label={`Role for ${shortId(member.userId)}`}
                            value={member.role}
                            disabled={busy}
                            onChange={(event) =>
                              void runAction(
                                "Role updated after server confirmation.",
                                () =>
                                  collaborationApi.changeRole(
                                    context.workspaceId,
                                    member.membershipId,
                                    event.target.value,
                                    idempotencyKey("role"),
                                  ),
                                {
                                  confirm:
                                    "Change this member’s role? Their available actions may be reduced immediately.",
                                  authority: true,
                                },
                              )
                            }
                          >
                            {ROLES.map((role) => (
                              <option key={role} value={role}>
                                {role}
                              </option>
                            ))}
                          </select>
                        ) : (
                          member.role
                        )}
                      </td>
                      <td>{member.state}</td>
                      <td className="collaboration-actions">
                        {has("membership.manage") && !protectedOwner && !isSelf && (
                          <>
                            {member.state === "active" ? (
                              <button
                                disabled={busy}
                                onClick={() =>
                                  void runAction(
                                    "Membership suspended.",
                                    () =>
                                      collaborationApi.membershipCommand(
                                        context.workspaceId,
                                        member.membershipId,
                                        "suspend",
                                        idempotencyKey("member-suspend"),
                                      ),
                                    {
                                      confirm:
                                        "Suspend this membership? Current access will be revoked.",
                                      authority: true,
                                    },
                                  )
                                }
                              >
                                Suspend
                              </button>
                            ) : (
                              member.state === "suspended" && (
                                <button
                                  disabled={busy}
                                  onClick={() =>
                                    void runAction("Membership restored.", () =>
                                      collaborationApi.membershipCommand(
                                        context.workspaceId,
                                        member.membershipId,
                                        "restore",
                                        idempotencyKey("member-restore"),
                                      ),
                                    )
                                  }
                                >
                                  Restore
                                </button>
                              )
                            )}
                            <button
                              className="danger"
                              disabled={busy || member.state === "removed"}
                              onClick={() =>
                                void runAction(
                                  "Membership removed.",
                                  () =>
                                    collaborationApi.membershipCommand(
                                      context.workspaceId,
                                      member.membershipId,
                                      "remove",
                                      idempotencyKey("member-remove"),
                                    ),
                                  {
                                    confirm:
                                      "Remove this membership? Access revocation is monotonic and takes effect immediately.",
                                    authority: true,
                                  },
                                )
                              }
                            >
                              Remove
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="collaboration-panel">
        <p className="eyebrow">Invitations</p>
        <h2>Invite a collaborator</h2>
        {has("invitation.create") && (
          <form
            className="collaboration-form collaboration-form--inline"
            onSubmit={(event) => {
              event.preventDefault();
              void runAction("Invitation created.", async () => {
                const result = await collaborationApi.createInvitation(context.workspaceId, {
                  recipientEmail: email,
                  intendedRole: inviteRole,
                  expiresInDays: 7,
                  idempotencyKey: idempotencyKey("invite"),
                });
                setEmail("");
                return result;
              });
            }}
          >
            <label>
              Recipient email
              <input
                type="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <label>
              Intended role
              <select
                value={inviteRole}
                onChange={(event) => setInviteRole(event.target.value as (typeof ROLES)[number])}
              >
                {ROLES.map((role) => (
                  <option key={role}>{role}</option>
                ))}
              </select>
            </label>
            <button disabled={busy}>Create invitation</button>
          </form>
        )}
        {!invitations.data?.length ? (
          <Empty>No invitations are visible.</Empty>
        ) : (
          <ul className="collaboration-records">
            {invitations.data.map((invitation) => (
              <li key={invitation.invitationId}>
                <div>
                  <strong>{invitation.recipientEmailMasked}</strong>
                  <span>
                    {invitation.intendedRole} · {invitation.state} · expires{" "}
                    {dateTime(invitation.expiresAt)}
                  </span>
                </div>
                {invitation.state === "pending" && (
                  <div className="collaboration-actions">
                    {has("invitation.resend") && (
                      <button
                        disabled={busy}
                        onClick={() =>
                          void runAction("Invitation resent.", () =>
                            collaborationApi.invitationCommand(
                              context.workspaceId,
                              invitation.invitationId,
                              "resend",
                              idempotencyKey("invite-resend"),
                            ),
                          )
                        }
                      >
                        Resend
                      </button>
                    )}
                    {has("invitation.revoke") && (
                      <button
                        className="danger"
                        disabled={busy}
                        onClick={() =>
                          void runAction(
                            "Invitation revoked.",
                            () =>
                              collaborationApi.invitationCommand(
                                context.workspaceId,
                                invitation.invitationId,
                                "revoke",
                                idempotencyKey("invite-revoke"),
                              ),
                            { confirm: "Revoke this pending invitation?" },
                          )
                        }
                      >
                        Revoke
                      </button>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        <details>
          <summary>Respond to an exact invitation</summary>
          <form className="collaboration-form" onSubmit={(event) => event.preventDefault()}>
            <label>
              Invitation ID
              <input value={inviteId} onChange={(event) => setInviteId(event.target.value)} />
            </label>
            <label>
              Invitation credential
              <input
                type="password"
                autoComplete="one-time-code"
                value={inviteToken}
                onChange={(event) => setInviteToken(event.target.value)}
              />
            </label>
            <div className="collaboration-actions">
              <button
                disabled={busy || !inviteId || !inviteToken}
                onClick={() =>
                  void runAction("Invitation accepted.", () =>
                    collaborationApi.invitationDecision(
                      inviteId,
                      "accept",
                      inviteToken,
                      idempotencyKey("invite-accept"),
                    ),
                  )
                }
              >
                Accept
              </button>
              <button
                disabled={busy || !inviteId || !inviteToken}
                onClick={() =>
                  void runAction("Invitation declined.", () =>
                    collaborationApi.invitationDecision(
                      inviteId,
                      "decline",
                      inviteToken,
                      idempotencyKey("invite-decline"),
                    ),
                  )
                }
              >
                Decline
              </button>
            </div>
          </form>
        </details>
      </section>

      {has("role.assign") && (
        <section className="collaboration-panel">
          <p className="eyebrow">Approval eligibility</p>
          <h2>Bounded reviewer assignments</h2>
          <p className="collaboration-note">
            Eligibility is not an approval and is not a capability grant. Milestone 4 policy,
            approval, scope, and separation-of-duty checks still apply.
          </p>
          <form
            className="collaboration-form collaboration-form--inline"
            onSubmit={(event) => {
              event.preventDefault();
              void runAction("Approval eligibility assigned.", () =>
                collaborationApi.assignApprovalAuthority(context.workspaceId, {
                  membershipId: approvalMember,
                  capability,
                  resourceKind: "canvas",
                  resourceId: approvalResource,
                  maximumRiskClass: "r3_durable_write",
                  expiresInDays: 7,
                  idempotencyKey: idempotencyKey("approval-authority"),
                }),
              );
            }}
          >
            <label>
              Eligible membership
              <select
                required
                value={approvalMember}
                onChange={(event) => setApprovalMember(event.target.value)}
              >
                <option value="">Select a member</option>
                {members.data
                  ?.filter(
                    (member) =>
                      member.state === "active" &&
                      ["administrator", "approver"].includes(member.role) &&
                      member.membershipId !== context.membershipId,
                  )
                  .map((member) => (
                    <option key={member.membershipId} value={member.membershipId}>
                      {shortId(member.userId)} · {member.role}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Capability
              <select
                value={capability}
                onChange={(event) =>
                  setCapability(event.target.value as (typeof CAPABILITIES)[number])
                }
              >
                {CAPABILITIES.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              Canvas resource ID
              <input
                required
                value={approvalResource}
                onChange={(event) => setApprovalResource(event.target.value)}
              />
            </label>
            <button disabled={busy}>Assign eligibility</button>
          </form>
          {!approvals.data?.length ? (
            <Empty>No approval-authority assignments are visible.</Empty>
          ) : (
            <ul className="collaboration-records">
              {approvals.data.map((approval) => (
                <li key={approval.assignmentId}>
                  <div>
                    <strong>{approval.capability}</strong>
                    <span>
                      {shortId(approval.membershipId)} · {approval.maximumRiskClass} ·{" "}
                      {approval.state}
                    </span>
                  </div>
                  {approval.state === "active" && (
                    <button
                      className="danger"
                      disabled={busy}
                      onClick={() =>
                        void runAction(
                          "Approval eligibility revoked.",
                          () =>
                            collaborationApi.revokeApprovalAuthority(
                              context.workspaceId,
                              approval.assignmentId,
                              idempotencyKey("approval-revoke"),
                            ),
                          { confirm: "Revoke this bounded review eligibility?", authority: true },
                        )
                      }
                    >
                      Revoke
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

function ResourceSelector({
  resourceKind,
  resourceId,
  setResourceKind,
  setResourceId,
}: {
  resourceKind: ResourceKind;
  resourceId: string;
  setResourceKind: (value: ResourceKind) => void;
  setResourceId: (value: string) => void;
}) {
  return (
    <div className="collaboration-form collaboration-form--inline">
      <label>
        Resource type
        <select
          value={resourceKind}
          onChange={(event) => setResourceKind(event.target.value as ResourceKind)}
        >
          {RESOURCE_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {kind.replace("_", " ")}
            </option>
          ))}
        </select>
      </label>
      <label>
        Exact resource ID
        <input
          value={resourceId}
          onChange={(event) => setResourceId(event.target.value.trim())}
          placeholder="UUID"
        />
      </label>
    </div>
  );
}

function Access({
  context,
  has,
  busy,
  resourceKind,
  resourceId,
  setResourceKind,
  setResourceId,
  runAction,
}: {
  context: CollaborationContext;
  has: (permission: CollaborationPermission) => boolean;
  busy: boolean;
  resourceKind: ResourceKind;
  resourceId: string;
  setResourceKind: (value: ResourceKind) => void;
  setResourceId: (value: string) => void;
  runAction: ActionRunner;
}) {
  const scope = collaborationKeys.scoped(
    context.authenticatedUserId,
    context.workspaceId,
    context.authorityGeneration,
  );
  const shares = useQuery({
    queryKey: [...scope, "shares"],
    queryFn: ({ signal }) => collaborationApi.shares(context.workspaceId, signal),
    enabled: has("resource.share"),
  });
  const ownership = useQuery({
    queryKey: resourceId
      ? collaborationKeys.resource(
          context.authenticatedUserId,
          context.workspaceId,
          context.authorityGeneration,
          resourceKind,
          resourceId,
        )
      : [...scope, "ownership-disabled"],
    queryFn: ({ signal }) =>
      collaborationApi.ownership(context.workspaceId, resourceKind, resourceId, signal),
    enabled: Boolean(resourceId),
    retry: false,
  });
  const transfers = useQuery({
    queryKey: [...scope, "ownership-transfers"],
    queryFn: ({ signal }) => collaborationApi.ownershipTransfers(context.workspaceId, signal),
  });
  const [audience, setAudience] = useState<"workspace" | "membership">("workspace");
  const [audienceMembership, setAudienceMembership] = useState("");
  const [access, setAccess] = useState<"view" | "contribute" | "manage">("view");
  const [recipient, setRecipient] = useState("");
  const [transferKind, setTransferKind] = useState<"workspace" | "resource">("resource");
  const [renderedAt] = useState(() => Date.now());
  const [selectedShareIds, setSelectedShareIds] = useState<string[]>([]);

  return (
    <div className="collaboration-stack">
      <section className="collaboration-panel">
        <p className="eyebrow">Typed resource</p>
        <h2>Visibility and ownership</h2>
        <ResourceSelector {...{ resourceKind, resourceId, setResourceKind, setResourceId }} />
        {ownership.isLoading && <p>Checking resource visibility…</p>}
        {ownership.isError && <ErrorState error={ownership.error} />}
        {ownership.data && (
          <dl className="collaboration-facts">
            <div>
              <dt>Owner</dt>
              <dd>
                {ownership.data.ownerKind} ·{" "}
                {shortId(ownership.data.ownerMembershipId ?? ownership.data.ownerUserId)}
              </dd>
            </div>
            <div>
              <dt>Visibility policy</dt>
              <dd>{ownership.data.visibilityPolicy.replaceAll("_", " ")}</dd>
            </div>
            <div>
              <dt>Authority state</dt>
              <dd>Generation {ownership.data.authorityGeneration}</dd>
            </div>
          </dl>
        )}
        {has("resource.share") && ownership.data && (
          <div className="collaboration-actions">
            {(["private", "inherit", "workspace_visible"] as const).map((policy) => (
              <button
                key={policy}
                disabled={busy || ownership.data.visibilityPolicy === policy}
                onClick={() =>
                  void runAction(
                    "Visibility updated after server confirmation.",
                    () =>
                      collaborationApi.setVisibility(
                        context.workspaceId,
                        resourceKind,
                        resourceId,
                        policy,
                        idempotencyKey("visibility"),
                      ),
                    {
                      confirm:
                        policy === "private"
                          ? "Make this resource private? Existing visibility may be revoked."
                          : undefined,
                      authority: true,
                    },
                  )
                }
              >
                {policy.replaceAll("_", " ")}
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="collaboration-panel">
        <p className="eyebrow">Sharing</p>
        <h2>Typed access records</h2>
        <p className="collaboration-note">
          View, contribute, and manage do not transfer ownership or grant workflow or agent
          invocation. Versions inherit their parent identity and cannot be shared independently.
        </p>
        {has("resource.share") && (
          <form
            className="collaboration-form collaboration-form--inline"
            onSubmit={(event) => {
              event.preventDefault();
              void runAction("Share created.", () =>
                collaborationApi.createShares(
                  context.workspaceId,
                  [
                    {
                      resourceKind,
                      resourceId,
                      audienceKind: audience,
                      audienceMembershipId: audience === "membership" ? audienceMembership : null,
                      accessLevel: access,
                      expiresInDays: null,
                    },
                  ],
                  idempotencyKey("share"),
                ),
              );
            }}
          >
            <label>
              Audience
              <select
                value={audience}
                onChange={(event) => setAudience(event.target.value as "workspace" | "membership")}
              >
                <option value="workspace">workspace</option>
                <option value="membership">membership</option>
              </select>
            </label>
            {audience === "membership" && (
              <label>
                Membership ID
                <input
                  required
                  value={audienceMembership}
                  onChange={(event) => setAudienceMembership(event.target.value)}
                />
              </label>
            )}
            <label>
              Access
              <select
                value={access}
                onChange={(event) =>
                  setAccess(event.target.value as "view" | "contribute" | "manage")
                }
              >
                <option>view</option>
                <option>contribute</option>
                <option>manage</option>
              </select>
            </label>
            <button disabled={busy || !resourceId}>Create share</button>
          </form>
        )}
        {!has("resource.share") ? (
          <Empty>Share administration is not available to your current membership.</Empty>
        ) : shares.isError ? (
          <ErrorState error={shares.error} />
        ) : !shares.data?.length ? (
          <Empty>No shares are visible.</Empty>
        ) : (
          <>
            <div className="collaboration-actions">
              <button
                className="danger"
                disabled={busy || !selectedShareIds.length}
                onClick={() =>
                  void runAction(
                    `${selectedShareIds.length} share record(s) revoked.`,
                    async () => {
                      const result = await collaborationApi.revokeShares(
                        context.workspaceId,
                        selectedShareIds,
                        idempotencyKey("share-bulk-revoke"),
                      );
                      setSelectedShareIds([]);
                      return result;
                    },
                    {
                      confirm: `Revoke ${selectedShareIds.length} selected share record(s)?`,
                      authority: true,
                    },
                  )
                }
              >
                Revoke selected
              </button>
            </div>
            <ul className="collaboration-records">
              {shares.data.map((share) => (
                <li key={share.shareId}>
                  <label className="collaboration-record-check">
                    <input
                      type="checkbox"
                      checked={selectedShareIds.includes(share.shareId)}
                      disabled={share.state !== "active"}
                      onChange={(event) =>
                        setSelectedShareIds((current) =>
                          event.target.checked
                            ? [...current, share.shareId].slice(0, 50)
                            : current.filter((item) => item !== share.shareId),
                        )
                      }
                    />
                    <span className="sr-only">
                      Select share for {share.resourceKind} {shortId(share.resourceId)}
                    </span>
                  </label>
                  <div>
                    <strong>
                      {share.resourceKind.replace("_", " ")} · {shortId(share.resourceId)}
                    </strong>
                    <span>
                      {share.audienceKind} · {share.accessLevel} · {share.state}
                      {share.expiresAt ? ` · expires ${dateTime(share.expiresAt)}` : ""}
                    </span>
                  </div>
                  {share.state === "active" && (
                    <button
                      className="danger"
                      disabled={busy}
                      onClick={() =>
                        void runAction(
                          "Share revoked.",
                          () =>
                            collaborationApi.revokeShares(
                              context.workspaceId,
                              [share.shareId],
                              idempotencyKey("share-revoke"),
                            ),
                          { confirm: "Revoke this share?", authority: true },
                        )
                      }
                    >
                      Revoke
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="collaboration-panel">
        <p className="eyebrow">Ownership transfer</p>
        <h2>Explicit pending requests</h2>
        <p className="collaboration-note">
          A pending request does not change ownership. Only the exact recipient may accept or reject
          it; only the requester may cancel it.
        </p>
        {has("ownership.transfer.request") && (
          <form
            className="collaboration-form collaboration-form--inline"
            onSubmit={(event) => {
              event.preventDefault();
              void runAction(
                "Ownership transfer requested. Ownership has not changed.",
                () =>
                  collaborationApi.requestOwnershipTransfer(context.workspaceId, {
                    transferKind,
                    recipientMembershipId: recipient,
                    resourceKind: transferKind === "resource" ? resourceKind : null,
                    resourceId: transferKind === "resource" ? resourceId : null,
                    expiresInHours: 48,
                    formerOwnerRole: "administrator",
                    idempotencyKey: idempotencyKey("ownership-transfer"),
                  }),
                { confirm: "Create this ownership-transfer request?" },
              );
            }}
          >
            <label>
              Transfer
              <select
                value={transferKind}
                onChange={(event) =>
                  setTransferKind(event.target.value as "workspace" | "resource")
                }
              >
                <option value="resource">resource</option>
                <option value="workspace">workspace</option>
              </select>
            </label>
            <label>
              Exact recipient membership
              <input
                required
                value={recipient}
                onChange={(event) => setRecipient(event.target.value)}
              />
            </label>
            <button disabled={busy || (transferKind === "resource" && !resourceId)}>
              Request transfer
            </button>
          </form>
        )}
        {transfers.isError ? (
          <ErrorState error={transfers.error} />
        ) : !transfers.data?.length ? (
          <Empty>No ownership-transfer records are visible.</Empty>
        ) : (
          <ul className="collaboration-records">
            {transfers.data.map((transfer) => {
              const expired =
                transfer.state === "pending" &&
                new Date(transfer.expiresAt).getTime() <= renderedAt;
              return (
                <li key={transfer.transferId}>
                  <div>
                    <strong>
                      {transfer.transferKind} transfer ·{" "}
                      {transfer.resourceId ? shortId(transfer.resourceId) : context.workspaceName}
                    </strong>
                    <span>
                      recipient {transfer.recipientMembershipId} ·{" "}
                      {expired ? "expired" : transfer.state} · {dateTime(transfer.expiresAt)}
                    </span>
                  </div>
                  {transfer.state === "pending" && !expired && (
                    <div className="collaboration-actions">
                      {transfer.recipientMembershipId === context.membershipId && (
                        <>
                          <button
                            disabled={busy}
                            onClick={() =>
                              void runAction(
                                "Ownership transfer accepted.",
                                () =>
                                  collaborationApi.ownershipTransferDecision(
                                    context.workspaceId,
                                    transfer.transferId,
                                    "accept",
                                    idempotencyKey("transfer-accept"),
                                  ),
                                {
                                  confirm:
                                    "Accept ownership? Current ownership and authority will change.",
                                  authority: true,
                                },
                              )
                            }
                          >
                            Accept
                          </button>
                          <button
                            disabled={busy}
                            onClick={() =>
                              void runAction("Ownership transfer rejected.", () =>
                                collaborationApi.ownershipTransferDecision(
                                  context.workspaceId,
                                  transfer.transferId,
                                  "reject",
                                  idempotencyKey("transfer-reject"),
                                ),
                              )
                            }
                          >
                            Reject
                          </button>
                        </>
                      )}
                      {transfer.requesterMembershipId === context.membershipId && (
                        <button
                          className="danger"
                          disabled={busy}
                          onClick={() =>
                            void runAction(
                              "Ownership transfer canceled.",
                              () =>
                                collaborationApi.ownershipTransferDecision(
                                  context.workspaceId,
                                  transfer.transferId,
                                  "cancel",
                                  idempotencyKey("transfer-cancel"),
                                ),
                              { confirm: "Cancel this ownership-transfer request?" },
                            )
                          }
                        >
                          Cancel
                        </button>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

function Discussions({
  context,
  has,
  busy,
  resourceKind,
  resourceId,
  setResourceKind,
  setResourceId,
  runAction,
}: {
  context: CollaborationContext;
  has: (permission: CollaborationPermission) => boolean;
  busy: boolean;
  resourceKind: ResourceKind;
  resourceId: string;
  setResourceKind: (value: ResourceKind) => void;
  setResourceId: (value: string) => void;
  runAction: ActionRunner;
}) {
  const resourceKey = resourceId
    ? collaborationKeys.resource(
        context.authenticatedUserId,
        context.workspaceId,
        context.authorityGeneration,
        resourceKind,
        resourceId,
      )
    : ["collaboration", "comments-disabled"];
  const comments = useQuery({
    queryKey: [...resourceKey, "comments"],
    queryFn: ({ signal }) =>
      collaborationApi.comments(context.workspaceId, resourceKind, resourceId, signal),
    enabled: Boolean(resourceId),
    retry: false,
  });
  const activity = useQuery({
    queryKey: [
      ...collaborationKeys.scoped(
        context.authenticatedUserId,
        context.workspaceId,
        context.authorityGeneration,
      ),
      "activity",
    ],
    queryFn: ({ signal }) => collaborationApi.activity(context.workspaceId, signal),
    enabled: has("collaboration_activity.view"),
  });
  const [content, setContent] = useState("");
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [historyId, setHistoryId] = useState("");
  const history = useQuery({
    queryKey: [...resourceKey, "comments", historyId, "revisions"],
    queryFn: ({ signal }) =>
      collaborationApi.commentRevisions(
        context.workspaceId,
        resourceKind,
        resourceId,
        historyId,
        signal,
      ),
    enabled: Boolean(historyId),
    retry: false,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void runAction("Comment recorded.", async () => {
      const result = await collaborationApi.createComment(
        context.workspaceId,
        resourceKind,
        resourceId,
        content,
        replyTo,
        idempotencyKey("comment"),
      );
      setContent("");
      setReplyTo(null);
      return result;
    });
  };

  return (
    <div className="collaboration-stack">
      <section className="collaboration-panel">
        <p className="eyebrow">Bounded discussion</p>
        <h2>Plain-text comments</h2>
        <p className="collaboration-note">
          Comments are collaboration records, never trusted source evidence. HTML, Markdown links,
          embeds, unsafe schemes, and control characters are rejected by the server.
        </p>
        <ResourceSelector {...{ resourceKind, resourceId, setResourceKind, setResourceId }} />
        {has("comment.create") && resourceId && (
          <form className="collaboration-form" onSubmit={submit}>
            <label htmlFor="comment-content">
              {replyTo ? `Reply to ${shortId(replyTo)}` : "New top-level comment"}
            </label>
            <textarea
              id="comment-content"
              maxLength={5_000}
              required
              value={content}
              onChange={(event) => setContent(event.target.value)}
              aria-describedby="comment-count"
            />
            <div className="collaboration-form-footer">
              <span id="comment-count">{[...content].length} / 5,000 characters</span>
              <div className="collaboration-actions">
                {replyTo && (
                  <button type="button" onClick={() => setReplyTo(null)}>
                    Cancel reply
                  </button>
                )}
                <button disabled={busy || !content.trim()}>Post comment</button>
              </div>
            </div>
          </form>
        )}
        {!resourceId ? (
          <Empty>Select an exact visible resource to load its comments.</Empty>
        ) : comments.isError ? (
          <ErrorState error={comments.error} />
        ) : comments.isLoading ? (
          <p>Loading comments…</p>
        ) : !comments.data?.length ? (
          <Empty>No comments are visible.</Empty>
        ) : (
          <ol className="collaboration-thread" aria-label="Comment thread">
            {comments.data.map((comment) => (
              <li
                key={comment.commentId}
                style={{ "--comment-depth": comment.depth } as React.CSSProperties}
              >
                <div>
                  <strong>{shortId(comment.authorUserId)}</strong>
                  <span>
                    {comment.state} · {dateTime(comment.updatedAt)}
                  </span>
                </div>
                <p>
                  {comment.content ??
                    (comment.state === "hidden_by_moderation"
                      ? "Comment hidden by moderation."
                      : "Comment removed by its author.")}
                </p>
                <div className="collaboration-actions">
                  {has("comment.create") && comment.depth < 4 && comment.content && (
                    <button onClick={() => setReplyTo(comment.commentId)}>Reply</button>
                  )}
                  {comment.revisionId && (
                    <button onClick={() => setHistoryId(comment.commentId)}>
                      Revision history
                    </button>
                  )}
                  {comment.authorUserId === context.authenticatedUserId && comment.content && (
                    <>
                      <button
                        onClick={() => {
                          const next = window.prompt(
                            "Revise this plain-text comment.",
                            comment.content ?? undefined,
                          );
                          if (!next || !comment.revisionId) return;
                          void runAction("Comment revision appended.", () =>
                            collaborationApi.reviseComment(
                              context.workspaceId,
                              resourceKind,
                              resourceId,
                              comment.commentId,
                              comment.revisionId!,
                              next,
                              idempotencyKey("comment-revise"),
                            ),
                          );
                        }}
                      >
                        Revise
                      </button>
                      <button
                        className="danger"
                        disabled={busy}
                        onClick={() =>
                          void runAction(
                            "Comment tombstone recorded.",
                            () =>
                              collaborationApi.tombstoneComment(
                                context.workspaceId,
                                resourceKind,
                                resourceId,
                                comment.commentId,
                                "remove_by_author",
                                idempotencyKey("comment-remove"),
                              ),
                            {
                              confirm: "Remove this comment while preserving its thread position?",
                            },
                          )
                        }
                      >
                        Remove
                      </button>
                    </>
                  )}
                  {has("comment.resolve") && comment.parentCommentId === null && (
                    <button
                      onClick={() =>
                        void runAction(
                          comment.threadState === "resolved"
                            ? "Thread reopened."
                            : "Thread resolved.",
                          () =>
                            collaborationApi.setThreadState(
                              context.workspaceId,
                              resourceKind,
                              resourceId,
                              comment.threadId,
                              comment.threadState === "resolved" ? "reopened" : "resolved",
                              idempotencyKey("thread-state"),
                            ),
                        )
                      }
                    >
                      {comment.threadState === "resolved" ? "Reopen" : "Resolve"}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
        {historyId && (
          <aside className="collaboration-history" aria-label="Immutable revision history">
            <div className="collaboration-section-heading">
              <h3>Revision history</h3>
              <button onClick={() => setHistoryId("")}>Close</button>
            </div>
            {history.isError ? (
              <ErrorState error={history.error} />
            ) : (
              <ol>
                {history.data?.map((revision) => (
                  <li key={revision.revisionId}>
                    <strong>Revision {revision.sequence}</strong>
                    <p>{revision.content}</p>
                  </li>
                ))}
              </ol>
            )}
          </aside>
        )}
      </section>

      <section className="collaboration-panel">
        <p className="eyebrow">activity-v1</p>
        <h2>Collaboration activity</h2>
        <p className="collaboration-note">
          This bounded projection excludes comment text, invitation credentials, and private audit,
          capability, approval, policy, and authority details.
        </p>
        {!has("collaboration_activity.view") ? (
          <Empty>Collaboration activity is not available to your current membership.</Empty>
        ) : activity.isError ? (
          <ErrorState error={activity.error} />
        ) : !activity.data?.length ? (
          <Empty>No collaboration activity is visible.</Empty>
        ) : (
          <ol className="collaboration-activity">
            {activity.data.map((event) => (
              <li key={event.activityId}>
                <strong>{event.eventType.replaceAll(".", " ")}</strong>
                <span>
                  {event.resourceKind.replace("_", " ")} {shortId(event.resourceId)} ·{" "}
                  {dateTime(event.occurredAt)}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

function Automations({
  context,
  busy,
  canvasId,
  setCanvasId,
  runAction,
}: {
  context: CollaborationContext;
  busy: boolean;
  canvasId: string;
  setCanvasId: (value: string) => void;
  runAction: ActionRunner;
}) {
  const canvases = useQuery({
    queryKey: ["canvases", context.workspaceId, context.authorityGeneration],
    queryFn: ({ signal }) => canvasApi.listCanvases(context.workspaceId, signal),
  });
  useEffect(() => {
    if (!canvasId && canvases.data?.length) setCanvasId(canvases.data[0]!.id);
  }, [canvasId, canvases.data, setCanvasId]);
  const workflows = useQuery({
    queryKey: collaborationKeys.automation(
      context.authenticatedUserId,
      context.workspaceId,
      context.authorityGeneration,
      canvasId,
      "workflows",
    ),
    queryFn: ({ signal }) => collaborationApi.workflows(context.workspaceId, canvasId, signal),
    enabled: Boolean(canvasId),
    retry: false,
  });
  const agents = useQuery({
    queryKey: collaborationKeys.automation(
      context.authenticatedUserId,
      context.workspaceId,
      context.authorityGeneration,
      canvasId,
      "agents",
    ),
    queryFn: ({ signal }) => collaborationApi.agents(context.workspaceId, canvasId, signal),
    enabled: Boolean(canvasId),
    retry: false,
  });
  const [query, setQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState("");
  const [seedIds, setSeedIds] = useState("");

  const invocationInput = (versionId: string) => ({
    versionId,
    query,
    selectedObjectIds: splitIds(selectedIds),
    seedObjectIds: splitIds(seedIds),
    idempotencyKey: idempotencyKey("shared-invocation"),
  });

  return (
    <div className="collaboration-stack">
      <section className="collaboration-panel">
        <p className="eyebrow">Selected approved context</p>
        <h2>Shared workflow and agent invocation</h2>
        <p className="collaboration-note">
          Discovery does not grant invocation. Each submission binds the current user, membership,
          workspace, canvas, identity, immutable version, and selected context, then the server
          evaluates authority again.
        </p>
        {canvases.isError ? (
          <ErrorState error={canvases.error} />
        ) : !canvases.data?.length ? (
          <Empty>No visible canvases are available in this workspace.</Empty>
        ) : (
          <div className="collaboration-form collaboration-form--inline">
            <label>
              Visible canvas
              <select value={canvasId} onChange={(event) => setCanvasId(event.target.value)}>
                {canvases.data.map((canvas) => (
                  <option key={canvas.id} value={canvas.id}>
                    {canvas.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Question
              <input
                value={query}
                maxLength={4_000}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <label>
              Selected object IDs, comma separated
              <input value={selectedIds} onChange={(event) => setSelectedIds(event.target.value)} />
            </label>
            <label>
              Seed object IDs, comma separated
              <input value={seedIds} onChange={(event) => setSeedIds(event.target.value)} />
            </label>
          </div>
        )}
      </section>

      <section className="collaboration-panel">
        <p className="eyebrow">Shared workflow identities</p>
        <h2>Workflows</h2>
        {workflows.isError ? (
          <ErrorState error={workflows.error} />
        ) : !workflows.data?.length ? (
          <Empty>No shared workflows are visible on this canvas.</Empty>
        ) : (
          <div className="collaboration-card-grid">
            {workflows.data.map((workflow) => {
              const active = workflow.versions.find(
                (version) => version.lifecycleState === "active",
              );
              return (
                <article key={workflow.definitionId} className="collaboration-record-card">
                  <Status>{workflow.visibilityBasis.replaceAll("_", " ")}</Status>
                  <h3>{workflow.name}</h3>
                  <p>{workflow.description}</p>
                  <dl>
                    <div>
                      <dt>Definition owner</dt>
                      <dd>{shortId(workflow.definitionOwnerUserId)}</dd>
                    </div>
                    <div>
                      <dt>Active version</dt>
                      <dd>
                        {active ? `v${active.versionNumber} · ${active.lifecycleState}` : "None"}
                      </dd>
                    </div>
                    <div>
                      <dt>Version lineage</dt>
                      <dd>
                        {workflow.versions.length} immutable version(s)
                        {active?.supersedesVersionId
                          ? ` · supersedes ${shortId(active.supersedesVersionId)}`
                          : ""}
                      </dd>
                    </div>
                  </dl>
                  <div className="collaboration-actions">
                    <Link href={`/universe?traceId=${workflow.traceId}`}>Trace</Link>
                    <button
                      disabled={
                        busy ||
                        !workflow.canInvoke ||
                        !active ||
                        !query.trim() ||
                        !splitIds(selectedIds).length ||
                        !splitIds(seedIds).length
                      }
                      title={
                        workflow.canInvoke
                          ? "The server will recheck invocation authority."
                          : "Visible, but invocation is not currently available."
                      }
                      onClick={() =>
                        active &&
                        void runAction("Workflow invocation started.", () =>
                          collaborationApi.startWorkflow(
                            context.workspaceId,
                            canvasId,
                            invocationInput(active.versionId),
                          ),
                        )
                      }
                    >
                      {workflow.canInvoke ? "Invoke workflow" : "Not invokable"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section className="collaboration-panel">
        <p className="eyebrow">Shared governed agent identities</p>
        <h2>Agents</h2>
        {agents.isError ? (
          <ErrorState error={agents.error} />
        ) : !agents.data?.length ? (
          <Empty>No shared agents are visible on this canvas.</Empty>
        ) : (
          <div className="collaboration-card-grid">
            {agents.data.map((agent) => {
              const active = agent.versions.find((version) => version.lifecycleState === "active");
              const binding = active?.workflowBindings[0];
              const certification = agent.validations.at(-1)?.outcome ?? "not available";
              return (
                <article key={agent.agentId} className="collaboration-record-card">
                  <Status>{agent.visibilityBasis.replaceAll("_", " ")}</Status>
                  <h3>{agent.displayName}</h3>
                  <p>{active?.purpose ?? agent.description}</p>
                  <dl>
                    <div>
                      <dt>Definition owner</dt>
                      <dd>{shortId(agent.definitionOwnerUserId)}</dd>
                    </div>
                    <div>
                      <dt>Lifecycle</dt>
                      <dd>
                        {agent.lifecycleState} · {active?.lifecycleState ?? "no active version"}
                      </dd>
                    </div>
                    <div>
                      <dt>Validation</dt>
                      <dd>{certification}</dd>
                    </div>
                    <div>
                      <dt>Communication profile</dt>
                      <dd>
                        {active?.communicationPolicy
                          ? "Bounded profile attached"
                          : "Default bounded profile"}
                      </dd>
                    </div>
                  </dl>
                  <div className="collaboration-actions">
                    <Link href={`/universe?traceId=${agent.traceId}`}>Trace</Link>
                    <button
                      disabled={
                        busy ||
                        !agent.canInvoke ||
                        !active ||
                        !binding ||
                        !query.trim() ||
                        !splitIds(selectedIds).length ||
                        !splitIds(seedIds).length
                      }
                      title={
                        agent.canInvoke
                          ? "The server will recheck collaboration, capability, approval, lifecycle, and policy authority."
                          : "Visible, but invocation is not currently available."
                      }
                      onClick={() =>
                        binding &&
                        void runAction("Agent invocation started.", () =>
                          collaborationApi.invokeAgent(
                            context.workspaceId,
                            canvasId,
                            agent.agentId,
                            {
                              workflowVersionId: binding.workflowVersionId,
                              query,
                              selectedObjectIds: splitIds(selectedIds),
                              seedObjectIds: splitIds(seedIds),
                              idempotencyKey: idempotencyKey("agent-invocation"),
                            },
                          ),
                        )
                      }
                    >
                      {agent.canInvoke ? "Invoke agent" : "Not invokable"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
