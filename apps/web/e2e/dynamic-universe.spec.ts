import { expect, test, type Page, type Route } from "@playwright/test";

const ids = {
  workspace: "10000000-0000-4000-8000-000000000001",
  canvas: "20000000-0000-4000-8000-000000000001",
  node: "30000000-0000-4000-8000-000000000001",
  execution: "40000000-0000-4000-8000-000000000001",
  definition: "50000000-0000-4000-8000-000000000001",
  version: "60000000-0000-4000-8000-000000000001",
  plan: "70000000-0000-4000-8000-000000000001",
  trace: "80000000-0000-4000-8000-000000000001",
  step: "90000000-0000-4000-8000-000000000001",
  retrieval: "a0000000-0000-4000-8000-000000000001",
  citation: "b0000000-0000-4000-8000-000000000001",
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

function workflow() {
  return {
    executionId: ids.execution,
    definitionId: ids.definition,
    versionId: ids.version,
    workspaceId: ids.workspace,
    canvasId: ids.canvas,
    status: "awaiting_approval",
    outcome: null,
    planId: ids.plan,
    planDigest: "a".repeat(64),
    inputDigest: "b".repeat(64),
    graphRevision: 4,
    selectedObjectIds: [ids.node],
    output: null,
    outputDigest: null,
    traceId: ids.trace,
    createdAt: timestamp,
    deadlineAt: "2026-07-25T19:00:00Z",
    cancelRequestedAt: null,
    completedAt: null,
    duplicate: false,
    steps: [
      {
        stepExecutionId: ids.step,
        stepKey: "approve",
        stepType: "human_approval",
        dependsOn: [],
        capability: "workflow.step.execute",
        riskClass: "r2_transient_action",
        requestedAction: "workflow.approval",
        affectedResourceId: null,
        status: "awaiting_approval",
        attemptCount: 0,
        maxAttempts: 1,
        approvalRequired: true,
        controlledExecutionId: null,
        approvalId: ids.plan,
        retrievalId: ids.retrieval,
        evidenceBundleId: null,
        effectId: null,
        rollbackResultId: null,
        safeFailureClass: null,
        outputDigest: null,
        startedAt: null,
        completedAt: null,
      },
    ],
  };
}

async function installUniverseAPI(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, "");
    if (method === "OPTIONS") {
      await route.fulfill({ status: 204 });
    } else if (path === "/workspaces") {
      await json(route, [
        {
          id: ids.workspace,
          name: "Universe workspace",
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
          name: "Evidence constellation",
          viewport: { x: 0, y: 0, zoom: 1 },
          revision: 3,
          createdAt: timestamp,
          updatedAt: timestamp,
        },
      ]);
    } else if (path === `/canvases/${ids.canvas}/universe-viewport`) {
      await json(route, {
        canvas: {
          id: ids.canvas,
          workspaceId: ids.workspace,
          name: "Evidence constellation",
          viewport: { x: 0, y: 0, zoom: 1 },
          revision: 3,
          createdAt: timestamp,
          updatedAt: timestamp,
        },
        canvasRevision: 3,
        graphRevision: 4,
        nodes: [
          {
            id: ids.node,
            canvasId: ids.canvas,
            type: "note",
            title: "Approved research note",
            text: "Selected evidence",
            position: { x: 80, y: 120 },
            width: 320,
            height: 240,
            revision: 1,
            createdAt: timestamp,
            updatedAt: timestamp,
          },
        ],
        edges: [],
        boundaryNodes: [],
        selectedNodes: [],
        nextCursor: null,
        bounded: false,
      });
    } else if (path.endsWith("/activity")) {
      await json(route, []);
    } else if (path.includes("/knowledge-graph/entities/")) {
      await json(route, []);
    } else if (path.endsWith(`/workflows/executions/${ids.execution}`)) {
      await json(route, workflow());
    } else if (path.endsWith(`/graph-retrievals/${ids.retrieval}/trace`)) {
      await json(route, {
        traceId: ids.trace,
        statuses: ["started", "succeeded"],
        eventTypes: ["graph_retrieval.started", "graph_retrieval.succeeded"],
        safeMetadata: [{ graphRevision: 4 }],
      });
    } else if (path.endsWith(`/graph-retrievals/${ids.retrieval}`)) {
      await json(route, {
        retrievalId: ids.retrieval,
        workspaceId: ids.workspace,
        canvasId: ids.canvas,
        query: "What is supported?",
        selectedObjectIds: [ids.node],
        seedObjectIds: [ids.node],
        graphRevision: 4,
        algorithmVersion: "bounded-graph-v1",
        schemaVersion: "graph-retrieval-v1",
        mode: "selected_graph",
        outcome: "supported",
        bounded: false,
        traceId: ids.trace,
        createdAt: timestamp,
        duplicate: false,
        decisions: [
          {
            decisionId: ids.definition,
            objectId: ids.node,
            relationshipId: null,
            included: true,
            reasonCode: "selected_context",
            distance: 0,
            rank: 1,
            score: 1,
            relationshipPath: [],
          },
        ],
        citations: [
          {
            citationId: ids.citation,
            canonicalObjectId: ids.node,
            canonicalVersion: 1,
            sourceVersion: 2,
            sourceSha256: "c".repeat(64),
            sourceTitle: "Approved research note",
            sourceType: "note",
            passageIdentity: "note:1",
            excerpt: "Selected evidence",
            excerptSha256: "d".repeat(64),
            locator: { section: "Summary" },
            relationshipPath: [],
            graphRevision: 4,
            ordinal: 1,
            citationSchemaVersion: "citation-v1",
            traceId: ids.trace,
          },
        ],
      });
    } else {
      await json(route, { detail: `Unhandled mock route: ${method} ${path}` }, 500);
    }
  });
}

test("Dynamic Universe direct navigation, context, evidence, workflow, and refresh remain usable", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await installUniverseAPI(page);
  const route = `/universe?workspaceId=${ids.workspace}&canvasId=${ids.canvas}&workflowExecutionId=${ids.execution}&retrievalId=${ids.retrieval}`;
  await page.goto(route);

  await expect(page.getByRole("heading", { name: "Dynamic Universe" })).toBeVisible();
  await expect(page.getByText("Approved research note", { exact: true }).first()).toBeVisible();
  const contextButton = page.getByRole("button", { name: "Remove" });
  await contextButton.focus();
  await page.keyboard.press("Enter");
  const selectButton = page.getByRole("button", { name: "Select" });
  await expect(selectButton).toBeVisible();
  await selectButton.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Remove" })).toBeVisible();

  await page.getByRole("button", { name: "Evidence" }).click();
  await expect(page.getByRole("heading", { name: "supported" })).toBeVisible();
  await expect(page.getByText("Selected evidence", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Workflow" }).click();
  await expect(page.getByText("awaiting approval", { exact: true }).first()).toBeVisible();
  await page.getByText("approve", { exact: true }).first().click();
  await expect(page.getByText("workflow.approval")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "Dynamic Universe" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("Dynamic Universe preserves essential inspection on a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installUniverseAPI(page);
  await page.goto(
    `/universe?workspaceId=${ids.workspace}&canvasId=${ids.canvas}&retrievalId=${ids.retrieval}`,
  );
  await expect(page.getByRole("navigation", { name: "Universe views" })).toBeVisible();
  await page.getByRole("button", { name: "Evidence" }).click();
  await expect(page.getByRole("heading", { name: "Exact citations" })).toBeVisible();
  await expect(page.locator("body")).not.toHaveCSS("overflow-x", "scroll");
});
