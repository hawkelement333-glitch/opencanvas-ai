import { describe, expect, it } from "vitest";

import {
  collaborationContextSchema,
  collaborationKeys,
  commentSchema,
  shareSchema,
  sharedAgentSchema,
} from "./collaboration-contracts";

const ids = {
  workspace: "00000000-0000-4000-8000-000000000001",
  user: "00000000-0000-4000-8000-000000000002",
  member: "00000000-0000-4000-8000-000000000003",
  resource: "00000000-0000-4000-8000-000000000004",
};

describe("collaboration contracts", () => {
  it("partitions cache keys by user, workspace, resource, and authority generation", () => {
    expect(collaborationKeys.canvases(ids.user, ids.workspace, 7)).toEqual([
      "collaboration",
      ids.user,
      ids.workspace,
      7,
      "canvases",
    ]);
    expect(collaborationKeys.canvases(ids.member, ids.workspace, 7)).not.toEqual(
      collaborationKeys.canvases(ids.user, ids.workspace, 7),
    );
    expect(
      collaborationKeys.resource(ids.user, ids.workspace, 7, "workflow", ids.resource),
    ).toEqual(["collaboration", ids.user, ids.workspace, 7, "workflow", ids.resource]);
    expect(
      collaborationKeys.resource(ids.user, ids.workspace, 8, "workflow", ids.resource),
    ).not.toEqual(collaborationKeys.resource(ids.user, ids.workspace, 7, "workflow", ids.resource));
  });

  it("fails closed on unknown roles, permissions, shares, and visibility values", () => {
    const context = {
      workspaceId: ids.workspace,
      workspaceName: "Atlas",
      workspaceLifecycleState: "active",
      workspaceOwnerUserId: ids.user,
      authenticatedUserId: ids.user,
      membershipId: ids.member,
      membershipState: "active",
      role: "super_admin",
      authorityGeneration: 1,
      permissionCeiling: ["everything"],
    };
    expect(collaborationContextSchema.safeParse(context).success).toBe(false);
    expect(
      shareSchema.safeParse({
        shareId: ids.member,
        workspaceId: ids.workspace,
        resourceKind: "workflow_version",
        resourceId: ids.resource,
        audienceKind: "everyone",
        audienceMembershipId: null,
        accessLevel: "invoke",
        state: "active",
        authorityGeneration: 1,
        expiresAt: null,
        duplicate: false,
      }).success,
    ).toBe(false);
  });

  it("preserves plain-text tombstones without accepting oversized comment content", () => {
    const base = {
      commentId: ids.resource,
      threadId: ids.member,
      workspaceId: ids.workspace,
      resourceKind: "canvas",
      resourceId: ids.resource,
      parentCommentId: null,
      depth: 0,
      threadSequence: 0,
      threadState: "open",
      state: "removed_by_author",
      revisionId: null,
      revisionSequence: null,
      content: null,
      authorUserId: ids.user,
      createdAt: "2026-07-26T12:00:00Z",
      updatedAt: "2026-07-26T12:00:00Z",
      duplicate: false,
    };
    expect(commentSchema.parse(base).content).toBeNull();
    expect(commentSchema.safeParse({ ...base, content: "x".repeat(5_001) }).success).toBe(false);
  });

  it("requires server-confirmed invocation state for shared agents", () => {
    expect(
      sharedAgentSchema.safeParse({
        agentId: ids.resource,
        workspaceId: ids.workspace,
        canvasId: ids.member,
        kind: "workflow_assistant",
        displayName: "Researcher",
        description: "Grounded research",
        lifecycleState: "active",
        traceId: ids.user,
        createdAt: "2026-07-26T12:00:00Z",
        versions: [],
        validations: [],
        activationRequests: [],
        invocations: [],
        evaluations: [],
        proposals: [],
        definitionOwnerUserId: ids.user,
        visibilityBasis: "direct_share",
      }).success,
    ).toBe(false);
  });
});
