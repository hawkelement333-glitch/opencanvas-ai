import { expect, test, type Page, type Route } from "@playwright/test";

const ids = {
  workspace: "10000000-0000-4000-8000-000000000001",
  canvas: "20000000-0000-4000-8000-000000000001",
  agent: "30000000-0000-4000-8000-000000000001",
  version: "40000000-0000-4000-8000-000000000001",
  workflow: "50000000-0000-4000-8000-000000000001",
  trace: "60000000-0000-4000-8000-000000000001",
  profile: "70000000-0000-4000-8000-000000000001",
  profileVersion: "80000000-0000-4000-8000-000000000001",
};
const timestamp = "2026-07-25T18:00:00Z";

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: {
      "Access-Control-Allow-Origin": "http://127.0.0.1:3000",
      "Access-Control-Allow-Credentials": "true",
      "Access-Control-Allow-Headers": "Content-Type,X-CSRF-Token",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    },
    body: JSON.stringify(body),
  });
}

const agent = {
  agentId: ids.agent,
  workspaceId: ids.workspace,
  canvasId: ids.canvas,
  kind: "workflow_assistant",
  displayName: "Grounded research helper",
  description: "Runs one approved selected-context workflow.",
  lifecycleState: "active",
  traceId: ids.trace,
  createdAt: timestamp,
  duplicate: false,
  versions: [
    {
      versionId: ids.version,
      versionNumber: 1,
      lifecycleState: "active",
      schemaVersion: "bounded-agent-definition-v1",
      purpose: "Answer grounded questions using the approved workflow.",
      promptTemplateVersion: "bounded-agent-prompt-v1",
      selectedContextPolicy: "required_explicit",
      provider: "mock",
      model: "mock-context-v1",
      limits: { maxWorkflowExecutions: 1 },
      communicationPolicy: { requireHumanAcceptance: true },
      evaluationPolicy: "human_review",
      riskClass: "r1_draft",
      contentDigest: "a".repeat(64),
      supersedesVersionId: null,
      traceId: ids.trace,
      createdAt: timestamp,
      workflowBindings: [
        { workflowVersionId: ids.workflow, workflowDigest: "b".repeat(64), ordinal: 0 },
      ],
      capabilityRequirements: [
        { capability: "context.selected.read", resourceKind: "canonical_object" },
      ],
    },
  ],
  validations: [],
  activationRequests: [],
  invocations: [],
  evaluations: [],
  proposals: [],
};

async function installAgentStudioApi(page: Page): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, "");
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204 });
    } else if (path === "/workspaces") {
      await json(route, [
        {
          id: ids.workspace,
          name: "Research workspace",
          description: null,
          ownerId: ids.workspace,
          version: 1,
          lifecycleState: "active",
          metadata: {},
          legacyCanvasId: ids.canvas,
          createdAt: timestamp,
          updatedAt: timestamp,
        },
      ]);
    } else if (path === "/canvases") {
      await json(route, [
        {
          id: ids.canvas,
          workspaceId: ids.workspace,
          name: "Evidence canvas",
          viewport: { x: 0, y: 0, zoom: 1 },
          revision: 1,
          createdAt: timestamp,
          updatedAt: timestamp,
        },
      ]);
    } else if (path.endsWith("/agent-studio/registries")) {
      await json(route, {
        registryVersion: "bounded-agent-registry-v1",
        agentKinds: ["workflow_assistant"],
        agentLifecycles: ["draft", "active", "suspended", "retired"],
        agentVersionLifecycles: ["draft", "active"],
        proposalKinds: ["agent_creation", "evaluation_recommendation"],
        validationOutcomes: ["valid"],
        evaluationOutcomes: ["meets_requirements", "insufficient_evidence"],
        capabilities: ["context.selected.read"],
        resourceKinds: ["canonical_object"],
        riskClasses: ["r1_draft"],
        providers: { mock: ["mock-context-v1"] },
        communication: {
          audiences: ["general"],
          readingLevels: ["standard"],
          formalities: ["neutral"],
          verbosities: ["balanced"],
          technicalDepths: ["medium"],
        },
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
    } else if (path.endsWith("/agent-studio/agents")) {
      await json(route, [agent]);
    } else if (path.endsWith("/agent-studio/communication-profiles")) {
      await json(route, [
        {
          profileId: ids.profile,
          profileVersionId: ids.profileVersion,
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
          contentDigest: "c".repeat(64),
          traceId: ids.trace,
          createdAt: timestamp,
        },
      ]);
    } else {
      await json(route, { detail: `Unhandled mock route: ${request.method()} ${path}` }, 500);
    }
  });
}

test("direct navigation and refresh preserve exact scoped Agent Studio state", async ({ page }) => {
  await installAgentStudioApi(page);
  await page.goto(
    `/agents?workspaceId=${ids.workspace}&canvasId=${ids.canvas}&agentId=${ids.agent}`,
  );

  await expect(page.getByRole("heading", { name: "Bounded Agent Studio" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Grounded research helper", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Server-derived authority scope/)).toBeVisible();
  await expect(
    page.getByText(/Visual proximity and future sharing never grant authority/),
  ).toBeVisible();
  await expect(page.getByText("mock / mock-context-v1")).toBeVisible();
  await expect(
    page.getByText("Answer grounded questions using the approved workflow."),
  ).toBeVisible();
  await expect(page.getByText(/system instruction/i)).toHaveCount(0);

  await page.getByRole("button", { name: "Communication" }).click();
  await expect(page.getByText(/Plain English · v1/)).toBeVisible();
  await expect(
    page.locator(".studio-profile-list").getByText(new RegExp(`canvas ${ids.canvas.slice(0, 8)}`)),
  ).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "Bounded Agent Studio" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Grounded research helper", exact: true }),
  ).toBeVisible();
});

test("Agent Studio remains usable in a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installAgentStudioApi(page);
  await page.goto(`/agents?workspaceId=${ids.workspace}&canvasId=${ids.canvas}`);

  await expect(page.getByRole("heading", { name: "Bounded Agent Studio" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Agent Studio sections" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Grounded research helper", exact: true }),
  ).toBeVisible();
  expect((await page.locator("body").evaluate((body) => body.scrollWidth)) <= 410).toBe(true);
});
