import { expect, test, type Page, type Route } from "@playwright/test";

const timestamp = "2026-07-17T12:00:00Z";
const workspaceId = "e2000000-0000-4000-8000-000000000002";
const canvas = {
  id: "canvas-doc",
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
      id: "note-1",
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
  let duplicateSequence = 1;
  let answerSequence = 0;

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
        id: "document-1",
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
        id: "document-node-1",
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
    if (path === "/documents/document-1" && method === "GET" && document) {
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
    if (path === "/documents/document-1/text" && method === "GET") {
      await json(route, {
        documentId: "document-1",
        fileName: "verified-facts.pdf",
        text: "Product brief\nThe verified launch date is October 14, 2026.",
        sections: [{ pageNumber: 2, heading: "Product brief", startOffset: 0, endOffset: 62 }],
      });
      return;
    }
    if (path === "/documents/document-1/chunks/chunk-1" && method === "GET") {
      await json(route, {
        documentId: "document-1",
        chunkId: "chunk-1",
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
    const nodeMatch = path.match(/^\/canvases\/canvas-doc\/nodes\/([^/]+)$/);
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
      /^\/canvases\/canvas-doc\/nodes\/(document-node-[^/]+)\/duplicate$/,
    );
    if (duplicateMatch && method === "POST" && document) {
      duplicateSequence += 1;
      const input = request.postDataJSON() as { position: { x: number; y: number } };
      const duplicate: MockNode = {
        ...(nodes.find((node) => node.id === duplicateMatch[1]) as MockNode),
        id: `document-node-${duplicateSequence}`,
        position: input.position,
        document,
      };
      nodes.push(duplicate);
      await json(route, duplicate, 201);
      return;
    }
    if (path === `/canvases/${canvas.id}/ai` && method === "POST") {
      answerSequence += 1;
      const input = request.postDataJSON() as { instruction: string; selectedNodeIds: string[] };
      const insufficient = input.instruction.toLowerCase().includes("annual revenue");
      const citations: MockCitation[] = insufficient
        ? []
        : [
            {
              id: "citation-1",
              sourceId: "S1",
              documentId: "document-1",
              documentTitle: "verified-facts.pdf",
              chunkId: "chunk-1",
              chunkIndex: 0,
              startOffset: 0,
              endOffset: 48,
              pageNumber: 2,
              heading: "Product brief",
              excerpt: "The verified launch date is October 14, 2026.",
              claim: "The launch date is October 14, 2026.",
              ordinal: 1,
            },
          ];
      const responseNode: MockNode = {
        id: `answer-${answerSequence}`,
        canvasId: canvas.id,
        type: "ai_response",
        title: insufficient ? "Insufficient evidence" : "Grounded answer",
        text: insufficient
          ? "The selected sources do not contain sufficient evidence about annual revenue."
          : "The launch date is October 14, 2026. [1]",
        position: { x: 820, y: 180 + answerSequence * 80 },
        width: 380,
        height: 280,
        revision: 0,
        citations,
        createdAt: timestamp,
        updatedAt: timestamp,
      };
      const generatedEdges: MockEdge[] = insufficient
        ? []
        : [
            {
              id: "source-edge-1",
              canvasId: canvas.id,
              sourceNodeId: responseNode.id,
              targetNodeId: "document-node-1",
              kind: "cites",
              label: "Source",
              revision: 0,
              createdAt: timestamp,
              updatedAt: timestamp,
            },
          ];
      nodes.push(responseNode);
      edges.push(...generatedEdges);
      await json(route, {
        requestId: `request-${answerSequence}`,
        responseId: `response-${answerSequence}`,
        traceId: "e2000000-0000-4000-8000-000000000004",
        node: responseNode,
        edges: generatedEdges,
        mock: true,
        grounded: !insufficient,
        insufficientEvidence: insufficient,
        citations,
      });
      return;
    }
    if (path === "/documents/document-1" && method === "DELETE") {
      const removed = new Set(
        nodes.filter((node) => node.document?.id === "document-1").map((node) => node.id),
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

test("upload, process, select, ground, cite, reject insufficient context, and delete", async ({
  page,
}) => {
  await installDocumentAPI(page);
  await page.goto("/");

  await page.getByTestId("document-file-input").setInputFiles({
    name: "verified-facts.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("mock PDF bytes"),
  });
  await expect(page.getByTestId("canvas-node-document-node-1")).toBeVisible();
  await expect(page.getByText("Extracting text")).toBeVisible();
  await expect(page.getByText("Ready", { exact: true })).toBeVisible({ timeout: 5_000 });

  await page.getByTestId("preview-document-document-node-1").click();
  await expect(page.getByTestId("document-preview")).toContainText(
    "The verified launch date is October 14, 2026.",
  );
  await page.getByLabel("Close document preview").click();

  await page.getByTestId("duplicate-node-document-node-1").click();
  await expect(page.getByTestId("canvas-node-document-node-2")).toBeVisible();
  await expect(page.getByTestId("canvas-node-document-node-2")).toContainText("verified-facts.pdf");

  await page.getByTestId("canvas-node-note-1").locator(".canvas-node__header").click();
  await page
    .getByTestId("canvas-node-document-node-1")
    .locator(".canvas-node__header")
    .click({ modifiers: ["Shift"] });
  await expect(page.getByTestId("selected-node-list").getByRole("listitem")).toHaveCount(2);

  await page.getByTestId("assistant-input").fill("What is the verified launch date?");
  await page.getByTestId("ask-assistant").click();
  await expect(page.getByText("Grounded response added with citations")).toBeVisible();
  await expect(page.getByTestId("canvas-node-answer-1")).toContainText("October 14, 2026");
  await page.getByTestId("citation-citation-1").click();
  await expect(page.getByTestId("source-passage")).toContainText(
    "The verified launch date is October 14, 2026.",
  );
  await expect(page.getByTestId("document-preview")).toContainText("Page 2");
  await page.getByLabel("Close document preview").click();

  await page.getByTestId("canvas-node-document-node-1").locator(".canvas-node__header").click();
  await page.getByTestId("assistant-input").fill("What is the annual revenue?");
  await page.getByTestId("ask-assistant").click();
  await expect(page.getByText(/lack sufficient evidence/i)).toBeVisible();
  await expect(page.getByTestId("canvas-node-answer-2")).toContainText(
    "do not contain sufficient evidence",
  );
  await expect(page.getByTestId("canvas-node-answer-2")).toContainText("No source citations");

  await page.getByTestId("delete-document-document-node-1").click();
  await expect(page.getByTestId("canvas-node-document-node-1")).toHaveCount(0);
  await expect(page.getByTestId("canvas-node-document-node-2")).toHaveCount(0);
});
