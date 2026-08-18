import { expect, test, type Page, type Route } from "@playwright/test";

const timestamp = "2026-07-17T12:00:00Z";
const workspaceId = "e2000000-0000-4000-8000-000000000002";
const canvasId = "e2000000-0000-4000-8000-000000000010";
const noteNodeId = "e2000000-0000-4000-8000-000000000011";
const documentId = "e2000000-0000-4000-8000-000000000012";
const documentNodeId = "e2000000-0000-4000-8000-000000000013";
const duplicateDocumentNodeId = "e2000000-0000-4000-8000-000000000014";
const chunkId = "e2000000-0000-4000-8000-000000000015";
const firstExecutionId = "e2000000-0000-4000-8000-000000000016";
const secondExecutionId = "e2000000-0000-4000-8000-000000000017";
const indexRequestId = "e2000000-0000-4000-8000-000000000022";
const indexTraceId = "e2000000-0000-4000-8000-000000000023";
const canvas = {
  id: canvasId,
  workspaceId,
  name: "Grounded research",
  viewport: { x: 0, y: 0, zoom: 1 },
  revision: 0,
  createdAt: timestamp,
  updatedAt: timestamp,
};

interface MockDocument {
  id: string;
  canvasId: string;
  fileName: string;
  fileType: "pdf";
  mediaType: string;
  fileSize: number;
  pageCount: number | null;
  status: "processing" | "ready" | "failed";
  processingStage: "extracting" | "ready" | "failed";
  errorMessage: string | null;
  chunkCount: number;
  createdAt: string;
  updatedAt: string;
}

interface MockCitation {
  id: string;
  sourceId: string;
  documentId: string;
  documentTitle: string;
  chunkId: string;
  chunkIndex: number;
  startOffset: number;
  endOffset: number;
  pageNumber: number | null;
  heading: string | null;
  excerpt: string;
  claim: string | null;
  ordinal: number;
}

interface MockNode {
  id: string;
  canvasId: string;
  type: "note" | "document" | "ai_response";
  title: string;
  text: string;
  position: { x: number; y: number };
  width: number;
  height: number;
  revision: number;
  document?: MockDocument | null;
  citations?: MockCitation[];
  createdAt: string;
  updatedAt: string;
}

interface MockEdge {
  id: string;
  canvasId: string;
  sourceNodeId: string;
  targetNodeId: string;
  kind: "default" | "generated_from" | "cites";
  label: string | null;
  revision: number;
  createdAt: string;
  updatedAt: string;
}

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: {
      "Access-Control-Allow-Origin": "http://127.0.0.1:3000",
      "Access-Control-Allow-Credentials": "true",
    },
    body: JSON.stringify(body),
  });
}

async function installDocumentAPI(page: Page): Promise<void> {
  let document: MockDocument | null = null;
  let nodes: MockNode[] = [
    {
      id: noteNodeId,
      canvasId: canvas.id,
      type: "note",
      title: "Launch question",
      text: "Confirm the launch date from the selected source.",
      position: { x: 80, y: 180 },
      width: 320,
      height: 240,
      revision: 0,
      createdAt: timestamp,
      updatedAt: timestamp,
    },
  ];
  let edges: MockEdge[] = [];
  let preparedInstruction = "";
  let indexState: "queued" | "canceled" = "queued";
  let documentPolls = 0;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, "");

    if (method === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "http://127.0.0.1:3000",
          "Access-Control-Allow-Credentials": "true",
        },
      });
      return;
    }
    if (path === "/health/runtime" && method === "GET") {
      await json(route, {
        mode: "live",
        appMode: "test",
        externalAiEnabled: false,
        label: "Test",
        demoCanvasId: null,
        demoTraceId: null,
      });
      return;
    }
    if (path === "/workspaces" && method === "GET") {
      await json(route, [
        {
          id: workspaceId,
          name: "Document E2E workspace",
          description: null,
          ownerId: null,
          version: 1,
          lifecycleState: "active",
          metadata: {},
          legacyCanvasId: null,
          createdAt: timestamp,
          updatedAt: timestamp,
        },
      ]);
      return;
    }
    if (path === "/canvases" && method === "GET") {
      await json(route, [canvas]);
      return;
    }
    if (path === `/canvases/${canvas.id}/snapshot` && method === "GET") {
      await json(route, { canvas, nodes, edges });
      return;
    }
    if (path === `/canvases/${canvas.id}/documents` && method === "POST") {
      document = {
        id: documentId,
        canvasId: canvas.id,
        fileName: "verified-facts.pdf",
        fileType: "pdf",
        mediaType: "application/pdf",
        fileSize: 1_024,
        pageCount: null,
        status: "processing",
        processingStage: "extracting",
        errorMessage: null,
        chunkCount: 0,
        createdAt: timestamp,
        updatedAt: timestamp,
      };
      const node: MockNode = {
        id: documentNodeId,
        canvasId: canvas.id,
        type: "document",
        title: document.fileName,
        text: "",
        position: { x: 440, y: 180 },
        width: 340,
        height: 280,
        revision: 0,
        document,
        createdAt: timestamp,
        updatedAt: timestamp,
      };
      nodes.push(node);
      await json(route, { document, node }, 201);
      return;
    }
    if (path === `/documents/${documentId}` && method === "GET" && document) {
      documentPolls += 1;
      if (documentPolls === 1) {
        await json(route, document);
        return;
      }
      document = {
        ...document,
        pageCount: 2,
        status: "ready",
        processingStage: "ready",
        chunkCount: 2,
      };
      nodes = nodes.map((node) =>
        node.document?.id === document?.id ? { ...node, document } : node,
      );
      await json(route, document);
      return;
    }
    if (path === `/documents/${documentId}/text` && method === "GET") {
      await json(route, {
        documentId,
        fileName: "verified-facts.pdf",
        text: "Product brief\nThe verified launch date is October 14, 2026.",
        sections: [{ pageNumber: 2, heading: "Product brief", startOffset: 0, endOffset: 62 }],
      });
      return;
    }
    if (path === `/documents/${documentId}/chunks/${chunkId}` && method === "GET") {
      await json(route, {
        documentId,
        chunkId,
        documentTitle: "verified-facts.pdf",
        pageNumber: 2,
        heading: "Product brief",
        chunkIndex: 0,
        startOffset: 0,
        endOffset: 62,
        text: "The verified launch date is October 14, 2026.",
      });
      return;
    }
    if (
      path === `/workspaces/${workspaceId}/canvases/${canvasId}/documents/${documentId}/reindex` &&
      method === "POST"
    ) {
      indexState = "queued";
      await json(
        route,
        {
          requestId: indexRequestId,
          workspaceId,
          canvasId,
          documentId,
          documentVersion: 1,
          operation: "reindex",
          state: indexState,
          reasonCode: "request_queued",
          traceId: indexTraceId,
          revisionId: null,
          publicationId: null,
          duplicate: false,
          cancellable: true,
          createdAt: timestamp,
          updatedAt: timestamp,
        },
        202,
      );
      return;
    }
    if (
      path ===
        `/workspaces/${workspaceId}/canvases/${canvasId}/index-requests/${indexRequestId}/cancel` &&
      method === "POST"
    ) {
      indexState = "canceled";
      await json(route, {
        requestId: indexRequestId,
        workspaceId,
        canvasId,
        documentId,
        documentVersion: 1,
        operation: "reindex",
        state: indexState,
        reasonCode: "user_canceled",
        traceId: indexTraceId,
        revisionId: null,
        publicationId: null,
        duplicate: false,
        cancellable: false,
        createdAt: timestamp,
        updatedAt: timestamp,
      });
      return;
    }
    const nodeMatch = path.match(new RegExp(`^/canvases/${canvasId}/nodes/([^/]+)$`));
    if (nodeMatch?.[1] && method === "PATCH") {
      const input = request.postDataJSON() as Partial<MockNode> & { revision: number };
      const current = nodes.find((node) => node.id === nodeMatch[1]);
      if (!current || current.revision !== input.revision) {
        await json(
          route,
          { detail: { code: "revision_conflict", message: "Stale revision" } },
          409,
        );
        return;
      }
      const saved: MockNode = {
        ...current,
        ...input,
        id: current.id,
        canvasId: current.canvasId,
        type: current.type,
        document: current.document,
        citations: current.citations,
        revision: current.revision + 1,
        updatedAt: timestamp,
      };
      nodes = nodes.map((node) => (node.id === saved.id ? saved : node));
      await json(route, saved);
      return;
    }
    const duplicateMatch = path.match(
      new RegExp(`^/canvases/${canvasId}/nodes/([^/]+)/duplicate$`),
    );
    if (duplicateMatch && method === "POST" && document) {
      const input = request.postDataJSON() as { position: { x: number; y: number } };
      const duplicate: MockNode = {
        ...(nodes.find((node) => node.id === duplicateMatch[1]) as MockNode),
        id: duplicateDocumentNodeId,
        position: input.position,
        document,
      };
      nodes.push(duplicate);
      await json(route, duplicate, 201);
      return;
    }
    if (
      path === `/workspaces/${workspaceId}/agent-executions/drafts/prepare` &&
      method === "POST"
    ) {
      const input = request.postDataJSON() as { instruction: string };
      preparedInstruction = input.instruction;
      await json(route, {
        executionId: preparedInstruction.toLowerCase().includes("annual revenue")
          ? secondExecutionId
          : firstExecutionId,
        status: "ready",
        duplicate: false,
      });
      return;
    }
    const runMatch = path.match(
      new RegExp(`^/workspaces/${workspaceId}/agent-executions/([^/]+)/run$`),
    );
    if (runMatch?.[1] && method === "POST") {
      const insufficient = preparedInstruction.toLowerCase().includes("annual revenue");
      await json(route, {
        executionId: runMatch[1],
        responseId: insufficient
          ? "e2000000-0000-4000-8000-000000000020"
          : "e2000000-0000-4000-8000-000000000018",
        traceId: insufficient
          ? "e2000000-0000-4000-8000-000000000021"
          : "e2000000-0000-4000-8000-000000000019",
        text: insufficient
          ? "The selected sources do not contain sufficient evidence about annual revenue."
          : "The launch date is October 14, 2026. [1]",
        insufficientEvidence: insufficient,
        citations: insufficient
          ? []
          : [
              {
                sourceId: "S1",
                documentId,
                documentVersion: 1,
                chunkId,
                claim: "The launch date is October 14, 2026.",
                quote: "The verified launch date is October 14, 2026.",
              },
            ],
        duplicate: false,
      });
      return;
    }
    if (path === `/documents/${documentId}` && method === "DELETE") {
      const removed = new Set(
        nodes.filter((node) => node.document?.id === documentId).map((node) => node.id),
      );
      nodes = nodes.filter((node) => !removed.has(node.id));
      edges = edges.filter(
        (edge) => !removed.has(edge.sourceNodeId) && !removed.has(edge.targetNodeId),
      );
      document = null;
      await route.fulfill({
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "http://127.0.0.1:3000",
          "Access-Control-Allow-Credentials": "true",
        },
      });
      return;
    }

    await json(route, { detail: `Unhandled mock route: ${method} ${path}` }, 500);
  });
}

test("selected context produces a read-only grounded draft with exact citations", async ({
  page,
}) => {
  await installDocumentAPI(page);
  await page.goto("/");

  await page.getByTestId("document-file-input").setInputFiles({
    name: "verified-facts.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("mock PDF bytes"),
  });
  await expect(page.getByTestId(`canvas-node-${documentNodeId}`)).toBeVisible();
  await expect(page.getByText("Extracting text")).toBeVisible();
  await expect(page.getByText("Ready", { exact: true })).toBeVisible({ timeout: 5_000 });

  await page.getByTestId(`preview-document-${documentNodeId}`).click();
  await expect(page.getByTestId("document-preview")).toContainText(
    "The verified launch date is October 14, 2026.",
  );
  await page.getByRole("button", { name: "Reindex document" }).click();
  await expect(page.getByTestId("document-preview").getByRole("status")).toContainText(
    "Index status: queued",
  );
  await page.getByRole("button", { name: "Cancel indexing" }).click();
  await expect(page.getByTestId("document-preview").getByRole("status")).toContainText(
    "Index status: canceled",
  );
  await page.getByLabel("Close document preview").click();

  await page.getByTestId(`duplicate-node-${documentNodeId}`).click();
  await expect(page.getByTestId(`canvas-node-${duplicateDocumentNodeId}`)).toBeVisible();
  await expect(page.getByTestId(`canvas-node-${duplicateDocumentNodeId}`)).toContainText(
    "verified-facts.pdf",
  );

  await page.getByTestId(`canvas-node-${noteNodeId}`).locator(".canvas-node__header").click();
  await page
    .getByTestId(`canvas-node-${documentNodeId}`)
    .locator(".canvas-node__header")
    .click({ modifiers: ["Shift"] });
  await expect(page.getByTestId("selected-node-list").getByRole("listitem")).toHaveCount(2);

  const groundedPrepare = page.waitForRequest(
    (request) =>
      request.url().endsWith("/agent-executions/drafts/prepare") && request.method() === "POST",
  );
  await page.getByTestId("controlled-draft-input").fill("What is the verified launch date?");
  await page.getByTestId("start-controlled-draft").click();
  const groundedRequest = (await groundedPrepare).postDataJSON() as {
    canvasId: string;
    instruction: string;
    selectedNodeIds: string[];
  };
  expect(groundedRequest).toMatchObject({
    canvasId,
    instruction: "What is the verified launch date?",
    selectedNodeIds: [noteNodeId, documentNodeId],
  });
  await expect(page.getByTestId("controlled-draft-result")).toContainText(
    "The launch date is October 14, 2026. [1]",
  );
  await expect(page.getByTestId("controlled-draft-result").getByRole("listitem")).toHaveCount(1);
  await page.getByRole("button", { name: "Citation [1]" }).click();
  await expect(page.getByTestId("source-passage")).toContainText(
    "The verified launch date is October 14, 2026.",
  );
  await expect(page.getByTestId("document-preview")).toContainText("Page 2");
  await page.getByLabel("Close document preview").click();
  await expect(page.locator(".react-flow__node")).toHaveCount(3);

  await page.getByTestId(`canvas-node-${documentNodeId}`).locator(".canvas-node__header").click();
  await page.getByTestId("controlled-draft-input").fill("What is the annual revenue?");
  await page.getByTestId("start-controlled-draft").click();
  await expect(page.getByTestId("controlled-draft-result")).toContainText(
    "do not contain sufficient evidence",
  );
  await expect(page.getByText("Insufficient evidence in the selected context")).toBeVisible();
  await expect(page.getByRole("list", { name: "Validated citations" })).toHaveCount(0);
  await expect(page.locator(".react-flow__node")).toHaveCount(3);

  await page.getByTestId(`delete-document-${documentNodeId}`).click();
  await expect(page.getByTestId(`canvas-node-${documentNodeId}`)).toHaveCount(0);
  await expect(page.getByTestId(`canvas-node-${duplicateDocumentNodeId}`)).toHaveCount(0);
});
