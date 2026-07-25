import { z } from "zod";

const uuid = z.string().uuid();
const timestamp = z.string().datetime({ offset: true });
const digest = z.string().regex(/^[0-9a-f]{64}$/);
const jsonObject = z.record(z.string(), z.unknown());

export const agentWorkflowBindingSchema = z.object({
  workflowVersionId: uuid,
  workflowDigest: digest,
  ordinal: z.number().int().nonnegative(),
});

export const agentCapabilityRequirementSchema = z.object({
  capability: z.string().min(1),
  resourceKind: z.string().min(1),
});

export const agentVersionSchema = z.object({
  versionId: uuid,
  versionNumber: z.number().int().positive(),
  lifecycleState: z.string().min(1),
  schemaVersion: z.literal("bounded-agent-definition-v1"),
  purpose: z.string().min(1),
  promptTemplateVersion: z.string().min(1),
  selectedContextPolicy: z.string().min(1),
  provider: z.string().min(1),
  model: z.string().min(1),
  limits: jsonObject,
  communicationPolicy: jsonObject,
  evaluationPolicy: z.string().min(1),
  riskClass: z.string().min(1),
  contentDigest: digest,
  supersedesVersionId: uuid.nullable().optional(),
  traceId: uuid,
  createdAt: timestamp,
  workflowBindings: z.array(agentWorkflowBindingSchema),
  capabilityRequirements: z.array(agentCapabilityRequirementSchema),
});

export const agentValidationSchema = z.object({
  validationId: uuid,
  agentVersionId: uuid,
  contentDigest: digest,
  outcome: z.string().min(1),
  issues: z.array(jsonObject),
  registryVersions: jsonObject,
  validatorVersion: z.string().min(1),
  traceId: uuid,
  createdAt: timestamp,
});

export const agentActivationRequestSchema = z.object({
  activationRequestId: uuid,
  agentVersionId: uuid,
  validationId: uuid,
  requestDigest: digest,
  authoritySummary: jsonObject,
  traceId: uuid,
  createdAt: timestamp,
  expiresAt: timestamp,
  decision: z.enum(["approved", "denied"]).nullable().optional(),
});

export const agentInvocationSchema = z.object({
  invocationId: uuid,
  agentId: uuid,
  agentVersionId: uuid,
  workflowVersionId: uuid,
  workflowExecutionId: uuid,
  workflowStatus: z.string().min(1),
  workflowOutcome: z.string().nullable().optional(),
  graphRevision: z.number().int().nonnegative(),
  traceId: uuid,
  createdAt: timestamp,
  duplicate: z.boolean().optional().default(false),
});

export const agentEvaluationSchema = z.object({
  evaluationId: uuid,
  invocationId: uuid,
  outcome: z.string().min(1),
  evidenceDigest: digest,
  summary: z.string().min(1),
  recommendations: z.array(jsonObject),
  traceId: uuid,
  createdAt: timestamp,
});

export const agentProposalSchema = z.object({
  proposalId: uuid,
  kind: z.string().min(1),
  sourceKind: z.string().min(1),
  agentId: uuid.nullable().optional(),
  sourceInvocationId: uuid.nullable().optional(),
  payload: jsonObject,
  payloadDigest: digest,
  traceId: uuid,
  createdAt: timestamp,
  decision: z.enum(["accepted", "rejected"]).nullable().optional(),
  resultingAgentId: uuid.nullable().optional(),
  resultingVersionId: uuid.nullable().optional(),
});

export const boundedAgentSchema = z.object({
  agentId: uuid,
  workspaceId: uuid,
  canvasId: uuid,
  kind: z.string().min(1),
  displayName: z.string().min(1),
  description: z.string().min(1),
  lifecycleState: z.string().min(1),
  traceId: uuid,
  createdAt: timestamp,
  versions: z.array(agentVersionSchema),
  validations: z.array(agentValidationSchema),
  activationRequests: z.array(agentActivationRequestSchema),
  invocations: z.array(agentInvocationSchema),
  evaluations: z.array(agentEvaluationSchema),
  proposals: z.array(agentProposalSchema),
  duplicate: z.boolean().optional().default(false),
});

export const agentRegistriesSchema = z.object({
  registryVersion: z.string().min(1),
  agentKinds: z.array(z.string().min(1)),
  agentLifecycles: z.array(z.string().min(1)),
  agentVersionLifecycles: z.array(z.string().min(1)),
  proposalKinds: z.array(z.string().min(1)),
  validationOutcomes: z.array(z.string().min(1)),
  evaluationOutcomes: z.array(z.string().min(1)),
  capabilities: z.array(z.string().min(1)),
  resourceKinds: z.array(z.string().min(1)),
  riskClasses: z.array(z.string().min(1)),
  providers: z.record(z.string(), z.array(z.string().min(1))),
  communication: z.record(z.string(), z.array(z.string().min(1))),
  serverMaximums: z.object({
    maxWorkflowExecutions: z.number().int().positive(),
    maxModelCalls: z.number().int().nonnegative(),
    maxRetrievalCalls: z.number().int().nonnegative(),
    maxEffects: z.number().int().nonnegative(),
    maxApprovals: z.number().int().nonnegative(),
    maxRetries: z.number().int().nonnegative(),
    maxDurationSeconds: z.number().int().positive(),
    maxInputChars: z.number().int().positive(),
    maxOutputChars: z.number().int().positive(),
    maxEvidenceBundleRequests: z.number().int().nonnegative(),
  }),
});

export const communicationProfileSchema = z.object({
  profileId: uuid,
  profileVersionId: uuid,
  workspaceId: uuid,
  canvasId: uuid,
  versionNumber: z.number().int().positive(),
  name: z.string().min(1),
  audience: z.string().min(1),
  readingLevel: z.string().min(1),
  formality: z.string().min(1),
  verbosity: z.string().min(1),
  technicalDepth: z.string().min(1),
  orwellRules: z.boolean(),
  contentDigest: digest,
  traceId: uuid,
  createdAt: timestamp,
});

export const communicationRevisionSchema = z.object({
  revisionId: uuid,
  profileVersionId: uuid,
  sourceInvocationId: uuid.nullable().optional(),
  originalText: z.string(),
  revisedText: z.string(),
  originalDigest: digest,
  revisedDigest: digest,
  protectedFactsDigest: digest,
  preservationStatus: z.string().min(1),
  safeFailureCode: z.string().nullable().optional(),
  traceId: uuid,
  createdAt: timestamp,
  decision: z.enum(["accepted", "rejected"]).nullable().optional(),
});

export type BoundedAgent = z.infer<typeof boundedAgentSchema>;
export type AgentVersion = z.infer<typeof agentVersionSchema>;
export type AgentRegistries = z.infer<typeof agentRegistriesSchema>;
export type AgentActivationRequest = z.infer<typeof agentActivationRequestSchema>;
export type AgentInvocation = z.infer<typeof agentInvocationSchema>;
export type CommunicationProfile = z.infer<typeof communicationProfileSchema>;
export type CommunicationRevision = z.infer<typeof communicationRevisionSchema>;
