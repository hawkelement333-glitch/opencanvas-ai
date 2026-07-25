import { describe, expect, it } from "vitest";

import {
  agentRegistriesSchema,
  boundedAgentSchema,
  communicationProfileSchema,
} from "./agent-studio-contracts";

const ids = {
  workspace: "10000000-0000-4000-8000-000000000001",
  canvas: "20000000-0000-4000-8000-000000000001",
  agent: "30000000-0000-4000-8000-000000000001",
  trace: "40000000-0000-4000-8000-000000000001",
};

describe("Agent Studio frontend contracts", () => {
  it("requires exact server-derived workspace and canvas scope on agents", () => {
    const base = {
      agentId: ids.agent,
      workspaceId: ids.workspace,
      canvasId: ids.canvas,
      kind: "workflow_assistant",
      displayName: "Grounded helper",
      description: "Runs one approved workflow.",
      lifecycleState: "draft",
      traceId: ids.trace,
      createdAt: "2026-07-25T18:00:00Z",
      versions: [],
      validations: [],
      activationRequests: [],
      invocations: [],
      evaluations: [],
      proposals: [],
      duplicate: false,
    };

    expect(boundedAgentSchema.parse(base).canvasId).toBe(ids.canvas);
    expect(boundedAgentSchema.safeParse({ ...base, canvasId: undefined }).success).toBe(false);
    expect(boundedAgentSchema.safeParse({ ...base, workspaceId: "client-current" }).success).toBe(
      false,
    );
  });

  it("requires exact scope on communication profiles", () => {
    const profile = {
      profileId: ids.agent,
      profileVersionId: ids.trace,
      workspaceId: ids.workspace,
      canvasId: ids.canvas,
      versionNumber: 1,
      name: "Plain English",
      audience: "general",
      readingLevel: "standard",
      formality: "neutral",
      verbosity: "balanced",
      technicalDepth: "medium",
      orwellRules: true,
      contentDigest: "a".repeat(64),
      traceId: ids.trace,
      createdAt: "2026-07-25T18:00:00Z",
    };

    expect(communicationProfileSchema.parse(profile).workspaceId).toBe(ids.workspace);
    expect(communicationProfileSchema.safeParse({ ...profile, canvasId: null }).success).toBe(
      false,
    );
  });

  it("accepts only bounded registry shapes from the server", () => {
    const parsed = agentRegistriesSchema.parse({
      registryVersion: "bounded-agent-registry-v1",
      agentKinds: ["workflow_assistant"],
      agentLifecycles: ["draft", "active"],
      agentVersionLifecycles: ["draft", "active"],
      proposalKinds: ["agent_creation"],
      validationOutcomes: ["valid"],
      evaluationOutcomes: ["meets_requirements"],
      capabilities: ["context.selected.read"],
      resourceKinds: ["canonical_object"],
      riskClasses: ["r1_draft"],
      providers: { mock: ["mock-context-v1"] },
      communication: { audiences: ["general"] },
      serverMaximums: {
        maxWorkflowExecutions: 8,
        maxModelCalls: 16,
        maxRetrievalCalls: 16,
        maxEffects: 4,
        maxApprovals: 8,
        maxRetries: 3,
        maxDurationSeconds: 900,
        maxInputChars: 60_000,
        maxOutputChars: 40_000,
        maxEvidenceBundleRequests: 4,
      },
    });

    expect(parsed.providers.mock).toEqual(["mock-context-v1"]);
    expect("systemInstruction" in parsed).toBe(false);
  });
});
