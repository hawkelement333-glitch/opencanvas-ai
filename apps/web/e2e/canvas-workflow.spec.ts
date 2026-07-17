import { expect, test, type Page, type Route } from "@playwright/test";

interface MockCanvas {
  id: string;
  name: string;
  viewport: { x: number; y: number; zoom: number };
  revision: number;
  createdAt: string;
  updatedAt: string;
}

interface MockNode {
  id: string;
  canvasId: string;
  type: "note" | "ai_response";
  title: string;
  text: string;
  position: { x: number; y: number };
  width: number;
  height: number;
  revision: number;
  createdAt: string;
  updatedAt: string;
}

interface MockEdge {
  id: string;
  canvasId: string;
  sourceNodeId: string;
  targetNodeId: string;
  kind: "default" | "generated_from";
  label: string | null;
  revision: number;
  createdAt: string;
  updatedAt: string;
}

function iso(): string {
  return new Date().toISOString();
}

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
    },
    body: JSON.stringify(body),
  });
}

async function installMockAPI(page: Page): Promise<void> {
  let canvas: MockCanvas | null = null;
  let nodes: MockNode[] = [];
  let edges: MockEdge[] = [];
  let nodeSequence = 0;
  let edgeSequence = 0;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/, "");

    if (method === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Headers": "Content-Type",
          "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
        },
      });
      return;
    }

    if (path === "/canvases" && method === "GET") {
      await json(route, canvas ? [canvas] : []);
      return;
    }

    if (path === "/canvases" && method === "POST") {
      const input = request.postDataJSON() as { name: string };
      const timestamp = iso();
      canvas = {
        id: "canvas-e2e",
        name: input.name,
        viewport: { x: 0, y: 0, zoom: 1 },
        revision: 0,
        createdAt: timestamp,
        updatedAt: timestamp,
      };
      await json(route, canvas, 201);
      return;
    }

    if (path === "/canvases/canvas-e2e/snapshot" && method === "GET" && canvas) {
      await json(route, { canvas, nodes, edges });
      return;
    }

    if (path === "/canvases/canvas-e2e/nodes" && method === "POST") {
      const input = request.postDataJSON() as Pick<
        MockNode,
        "type" | "title" | "text" | "position" | "width" | "height"
      >;
      nodeSequence += 1;
      const timestamp = iso();
      const created: MockNode = {
        id: `node-${nodeSequence}`,
        canvasId: "canvas-e2e",
        revision: 0,
        createdAt: timestamp,
        updatedAt: timestamp,
        ...input,
      };
      nodes.push(created);
      await json(route, created, 201);
      return;
    }

    const nodeMatch = path.match(/^\/canvases\/canvas-e2e\/nodes\/([^/]+)$/);
    if (nodeMatch?.[1] && method === "PATCH") {
      const id = nodeMatch[1];
      const input = request.postDataJSON() as Partial<MockNode> & { revision: number };
      const current = nodes.find((node) => node.id === id);
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
        revision: current.revision + 1,
        updatedAt: iso(),
      };
      nodes = nodes.map((node) => (node.id === id ? saved : node));
      await json(route, saved);
      return;
    }

    if (nodeMatch?.[1] && method === "DELETE") {
      const id = nodeMatch[1];
      nodes = nodes.filter((node) => node.id !== id);
      edges = edges.filter((edge) => edge.sourceNodeId !== id && edge.targetNodeId !== id);
      await route.fulfill({ status: 204, headers: { "Access-Control-Allow-Origin": "*" } });
      return;
    }

    if (path === "/canvases/canvas-e2e/edges" && method === "POST") {
      const input = request.postDataJSON() as Pick<
        MockEdge,
        "sourceNodeId" | "targetNodeId" | "kind" | "label"
      >;
      edgeSequence += 1;
      const timestamp = iso();
      const created: MockEdge = {
        id: `edge-${edgeSequence}`,
        canvasId: "canvas-e2e",
        revision: 0,
        createdAt: timestamp,
        updatedAt: timestamp,
        ...input,
      };
      edges.push(created);
      await json(route, created, 201);
      return;
    }

    const edgeMatch = path.match(/^\/canvases\/canvas-e2e\/edges\/([^/]+)$/);
    if (edgeMatch?.[1] && method === "DELETE") {
      edges = edges.filter((edge) => edge.id !== edgeMatch[1]);
      await route.fulfill({ status: 204, headers: { "Access-Control-Allow-Origin": "*" } });
      return;
    }

    if (path === "/canvases/canvas-e2e/ai" && method === "POST") {
      const input = request.postDataJSON() as { instruction: string; selectedNodeIds: string[] };
      nodeSequence += 1;
      const timestamp = iso();
      const responseNode: MockNode = {
        id: `node-${nodeSequence}`,
        canvasId: "canvas-e2e",
        type: "ai_response",
        title: "AI synthesis",
        text: `Mock synthesis for: ${input.instruction}`,
        position: { x: 720, y: 240 },
        width: 360,
        height: 260,
        revision: 0,
        createdAt: timestamp,
        updatedAt: timestamp,
      };
      const generatedEdges = input.selectedNodeIds.map<MockEdge>((sourceNodeId) => {
        edgeSequence += 1;
        return {
          id: `edge-${edgeSequence}`,
          canvasId: "canvas-e2e",
          sourceNodeId,
          targetNodeId: responseNode.id,
          kind: "generated_from",
          label: null,
          revision: 0,
          createdAt: timestamp,
          updatedAt: timestamp,
        };
      });
      nodes.push(responseNode);
      edges.push(...generatedEdges);
      await json(route, {
        requestId: "request-e2e",
        responseId: "response-e2e",
        node: responseNode,
        edges: generatedEdges,
        mock: true,
      });
      return;
    }

    await json(route, { detail: `Unhandled mock route: ${method} ${path}` }, 500);
  });
}

test("create, save, restore, connect, query, edit AI response, and restore again", async ({
  page,
}) => {
  await installMockAPI(page);
  await page.goto("/");

  await page.getByTestId("empty-create-canvas").click();
  await expect(
    page.getByLabel("Canvas toolbar").getByText("My first canvas", { exact: true }),
  ).toBeVisible();

  await page.getByTestId("add-note").click();
  await expect(page.getByTestId("canvas-node-node-1")).toBeVisible();
  await page.getByTestId("node-title-node-1").fill("Customer problem");
  await page.getByTestId("node-text-node-1").fill("Teams lose context across disconnected tools.");

  await page.getByTestId("add-note").click();
  await expect(page.getByTestId("canvas-node-node-2")).toBeVisible();
  await page.getByTestId("node-title-node-2").fill("Product thesis");
  await page.getByTestId("node-text-node-2").fill("A spatial graph keeps the reasoning visible.");
  await page.getByTestId("save-canvas").click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("node-text-node-1")).toHaveValue(
    "Teams lose context across disconnected tools.",
  );
  await expect(page.getByTestId("node-text-node-2")).toHaveValue(
    "A spatial graph keeps the reasoning visible.",
  );

  await page.getByTestId("canvas-node-node-1").locator(".canvas-node__header").click();
  await page
    .getByTestId("canvas-node-node-2")
    .locator(".canvas-node__header")
    .click({ modifiers: ["Shift"] });
  await expect(page.getByTestId("selected-node-list").getByRole("listitem")).toHaveCount(2);
  const edgeCreated = page.waitForResponse(
    (response) => response.url().endsWith("/edges") && response.request().method() === "POST",
  );
  await page.getByTestId("connect-selected").click();
  expect((await edgeCreated).status()).toBe(201);
  await expect(page.locator(".react-flow__edge")).toHaveCount(1);

  const edge = page.locator(".react-flow__edge").first();
  await edge.dispatchEvent("click");
  await expect(edge).toHaveClass(/selected/);
  const edgeDeleted = page.waitForResponse(
    (response) => response.url().includes("/edges/") && response.request().method() === "DELETE",
  );
  await page.keyboard.press("Delete");
  expect((await edgeDeleted).status()).toBe(204);
  await expect(page.locator(".react-flow__edge")).toHaveCount(0);

  await page.getByTestId("canvas-node-node-1").locator(".canvas-node__header").click();
  await page
    .getByTestId("canvas-node-node-2")
    .locator(".canvas-node__header")
    .click({ modifiers: ["Shift"] });
  await page
    .getByTestId("assistant-input")
    .fill("What product direction follows from these notes?");
  await page.getByTestId("ask-assistant").click();

  await expect(page.getByTestId("canvas-node-node-3")).toBeVisible();
  await expect(page.getByText("Response added to your canvas")).toBeVisible();
  await page.getByTestId("node-text-node-3").fill("Edited mock synthesis that should persist.");
  await page.getByTestId("save-canvas").click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("node-text-node-3")).toHaveValue(
    "Edited mock synthesis that should persist.",
  );
});
