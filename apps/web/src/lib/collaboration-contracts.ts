import { z } from "zod";

import { boundedAgentSchema } from "./agent-studio-contracts";

const uuid = z.string().uuid();
const timestamp = z.string().datetime({ offset: true });

export const collaborationRoleSchema = z.enum([
  "owner",
  "administrator",
  "editor",
  "approver",
  "member",
  "viewer",
]);
export const assignableRoleSchema = z.enum([
  "administrator",
  "editor",
  "approver",
  "member",
  "viewer",
]);
export const collaborationPermissionSchema = z.enum([
  "workspace.view",
  "workspace.settings.manage",
  "membership.view",
  "membership.manage",
  "invitation.create",
  "invitation.resend",
  "invitation.revoke",
  "role.assign",
  "ownership.transfer.request",
  "ownership.transfer.accept",
  "ownership.transfer.cancel",
  "canvas.view",
  "canvas.edit",
  "canvas.share",
  "resource.view",
  "resource.edit",
  "resource.share",
  "comment.create",
  "comment.edit_own",
  "comment.resolve",
  "comment.moderate",
  "workflow.view",
  "workflow.edit",
  "workflow.share",
  "workflow.invoke",
  "agent.view",
  "agent.edit",
  "agent.share",
  "agent.activate_request",
  "agent.invoke",
  "approval.review",
  "collaboration_activity.view",
  "trace.view",
  "source.export",
  "evidence_bundle.view",
  "evidence_bundle.export",
]);
export const resourceKindSchema = z.enum(["canvas", "canonical_object", "workflow", "agent"]);
export const shareAccessSchema = z.enum(["view", "contribute", "manage"]);
export const shareAudienceSchema = z.enum(["workspace", "membership"]);
export const visibilityPolicySchema = z.enum(["private", "inherit", "workspace_visible"]);
export const visibilityBasisSchema = z.enum([
  "resource_owner",
  "direct_share",
  "workspace_visible",
  "inherited_access",
]);

export const collaborationContextSchema = z.object({
  workspaceId: uuid,
  workspaceName: z.string().min(1).max(160),
  workspaceLifecycleState: z.enum(["created", "active", "archived", "deleted"]),
  workspaceOwnerUserId: uuid,
  authenticatedUserId: uuid,
  membershipId: uuid,
  membershipState: z.literal("active"),
  role: collaborationRoleSchema,
  authorityGeneration: z.number().int().positive(),
  permissionCeiling: z.array(collaborationPermissionSchema).max(36),
});

export const membershipSchema = z.object({
  membershipId: uuid,
  userId: uuid,
  workspaceId: uuid,
  role: collaborationRoleSchema,
  state: z.enum(["active", "suspended", "removed"]),
  authorityGeneration: z.number().int().positive(),
  acceptedInvitationId: uuid.nullable(),
  createdAt: timestamp,
  stateRecordedAt: timestamp,
});

export const invitationSchema = z.object({
  invitationId: uuid,
  workspaceId: uuid,
  recipientEmailMasked: z.string().min(1),
  intendedRole: assignableRoleSchema,
  state: z.enum(["pending", "accepted", "declined", "expired", "revoked"]),
  expiresAt: timestamp,
  createdAt: timestamp,
  stateRecordedAt: timestamp,
  duplicate: z.boolean().default(false),
  developmentToken: z.string().nullable().optional(),
});

export const approvalAuthoritySchema = z.object({
  assignmentId: uuid,
  workspaceId: uuid,
  membershipId: uuid,
  capability: z.string().min(1),
  resourceKind: z.string().min(1),
  resourceId: uuid,
  maximumRiskClass: z.string().min(1),
  state: z.enum(["active", "revoked", "superseded"]),
  validFrom: timestamp,
  expiresAt: timestamp,
  duplicate: z.boolean().default(false),
});

export const shareSchema = z.object({
  shareId: uuid,
  workspaceId: uuid,
  resourceKind: resourceKindSchema,
  resourceId: uuid,
  audienceKind: shareAudienceSchema,
  audienceMembershipId: uuid.nullable(),
  accessLevel: shareAccessSchema,
  state: z.enum(["active", "revoked", "expired", "superseded"]),
  authorityGeneration: z.number().int().positive(),
  expiresAt: timestamp.nullable(),
  duplicate: z.boolean().default(false),
});

export const resourceOwnershipSchema = z.object({
  resourceKind: resourceKindSchema,
  resourceId: uuid,
  ownerKind: z.enum(["workspace", "membership"]),
  ownerMembershipId: uuid.nullable(),
  ownerUserId: uuid.nullable(),
  visibilityPolicy: visibilityPolicySchema,
  authorityGeneration: z.number().int().positive(),
});

export const ownershipTransferSchema = z.object({
  transferId: uuid,
  workspaceId: uuid,
  transferKind: z.enum(["workspace", "resource"]),
  resourceKind: resourceKindSchema.nullable(),
  resourceId: uuid.nullable(),
  requesterMembershipId: uuid,
  recipientMembershipId: uuid,
  state: z.enum(["pending", "accepted", "rejected", "canceled", "expired", "superseded"]),
  authorityGeneration: z.number().int().positive(),
  expiresAt: timestamp,
  duplicate: z.boolean().default(false),
});

export const commentSchema = z.object({
  commentId: uuid,
  threadId: uuid,
  workspaceId: uuid,
  resourceKind: resourceKindSchema,
  resourceId: uuid,
  parentCommentId: uuid.nullable(),
  depth: z.number().int().min(0).max(4),
  threadSequence: z.number().int().nonnegative(),
  threadState: z.enum(["open", "resolved", "reopened"]),
  state: z.enum(["active", "edited", "hidden_by_moderation", "removed_by_author"]),
  revisionId: uuid.nullable(),
  revisionSequence: z.number().int().nonnegative().nullable(),
  content: z.string().max(5_000).nullable(),
  authorUserId: uuid,
  createdAt: timestamp,
  updatedAt: timestamp,
  duplicate: z.boolean().default(false),
});

export const commentRevisionSchema = z.object({
  revisionId: uuid,
  commentId: uuid,
  sequence: z.number().int().nonnegative(),
  revisionKind: z.enum(["created", "edited"]),
  authorUserId: uuid,
  content: z.string().max(5_000),
  contentDigest: z.string().regex(/^[0-9a-f]{64}$/),
  traceId: uuid,
  createdAt: timestamp,
  duplicate: z.boolean().default(false),
});

export const commentThreadSchema = z.object({
  threadId: uuid,
  workspaceId: uuid,
  resourceKind: resourceKindSchema,
  resourceId: uuid,
  state: z.enum(["open", "resolved", "reopened"]),
  updatedAt: timestamp,
  duplicate: z.boolean().default(false),
});

export const collaborationActivitySchema = z.object({
  activityId: uuid,
  eventId: uuid,
  eventType: z.enum([
    "comment.created",
    "comment.reply.created",
    "comment.revised",
    "comment.tombstoned",
    "comment.thread.resolved",
    "comment.thread.reopened",
    "resource.share.created",
    "resource.share.changed",
    "resource.share.revoked",
    "resource.visibility.changed",
    "resource.ownership_changed",
  ]),
  workspaceId: uuid,
  canvasId: uuid.nullable(),
  sequence: z.number().int().positive(),
  resourceKind: resourceKindSchema,
  resourceId: uuid,
  commentId: uuid.nullable(),
  threadId: uuid.nullable(),
  actorUserId: uuid,
  traceId: uuid,
  occurredAt: timestamp,
});

const workflowVersionSchema = z.object({
  versionId: uuid,
  versionNumber: z.number().int().positive(),
  lifecycleState: z.string().min(1),
  schemaVersion: z.string().min(1),
  inputSchemaVersion: z.string().min(1),
  outputSchemaVersion: z.string().min(1),
  contentDigest: z.string().regex(/^[0-9a-f]{64}$/),
  maxSteps: z.number().int().positive(),
  maxDurationSeconds: z.number().int().positive(),
  maxRetriesPerStep: z.number().int().nonnegative(),
  compensationPolicy: z.string().min(1),
  supersedesVersionId: uuid.nullable(),
  traceId: uuid,
  createdAt: timestamp,
});

export const sharedWorkflowSchema = z.object({
  definitionId: uuid,
  workspaceId: uuid,
  canvasId: uuid,
  kind: z.string().min(1),
  name: z.string().min(1),
  description: z.string(),
  definitionOwnerUserId: uuid,
  visibilityBasis: visibilityBasisSchema,
  canInvoke: z.boolean(),
  schemaVersion: z.string().min(1),
  traceId: uuid,
  createdAt: timestamp,
  versions: z.array(workflowVersionSchema),
  duplicate: z.boolean().default(false),
});

export const sharedAgentSchema = boundedAgentSchema.extend({
  definitionOwnerUserId: uuid,
  visibilityBasis: visibilityBasisSchema,
  canInvoke: z.boolean(),
});

export const collaborationKeys = {
  context: (userId: string, workspaceId: string) =>
    ["collaboration-context", userId, workspaceId] as const,
  scoped: (userId: string, workspaceId: string, authorityGeneration: number) =>
    ["collaboration", userId, workspaceId, authorityGeneration] as const,
  canvases: (userId: string, workspaceId: string, authorityGeneration: number) =>
    ["collaboration", userId, workspaceId, authorityGeneration, "canvases"] as const,
  resource: (
    userId: string,
    workspaceId: string,
    authorityGeneration: number,
    resourceKind: string,
    resourceId: string,
  ) =>
    ["collaboration", userId, workspaceId, authorityGeneration, resourceKind, resourceId] as const,
  automation: (
    userId: string,
    workspaceId: string,
    authorityGeneration: number,
    canvasId: string,
    kind: "workflows" | "agents",
  ) => ["collaboration", userId, workspaceId, authorityGeneration, canvasId, kind] as const,
};

export type CollaborationContext = z.infer<typeof collaborationContextSchema>;
export type CollaborationPermission = z.infer<typeof collaborationPermissionSchema>;
export type Membership = z.infer<typeof membershipSchema>;
export type Invitation = z.infer<typeof invitationSchema>;
export type ApprovalAuthority = z.infer<typeof approvalAuthoritySchema>;
export type ResourceKind = z.infer<typeof resourceKindSchema>;
export type Share = z.infer<typeof shareSchema>;
export type ResourceOwnership = z.infer<typeof resourceOwnershipSchema>;
export type OwnershipTransfer = z.infer<typeof ownershipTransferSchema>;
export type CollaborationComment = z.infer<typeof commentSchema>;
export type CollaborationActivity = z.infer<typeof collaborationActivitySchema>;
export type SharedWorkflow = z.infer<typeof sharedWorkflowSchema>;
export type SharedAgent = z.infer<typeof sharedAgentSchema>;
