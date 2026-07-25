import { afterEach, describe, expect, it, vi } from "vitest";

import { agentStudioApi } from "./api-client";

const ids = {
  workspace: "10000000-0000-4000-8000-000000000001",
  canvas: "20000000-0000-4000-8000-000000000001",
  agent: "30000000-0000-4000-8000-000000000001",
  trace: "40000000-0000-4000-8000-000000000001",
};

const agent = {
  agentId: ids.agent,
  workspaceId: ids.workspace,
  canvasId: ids.canvas,
  kind: "workflow_assistant",
  displayName: "Bounded helper",
  description: "Runs one approved workflow.",
  lifecycleState: "suspended",
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

afterEach(() => {
  vi.restoreAllMocks();
  document.cookie = "mobius_session_csrf=; Max-Age=0";
});

describe("Agent Studio API client", () => {
  it("uses exact opaque scope, CSRF, and closed lifecycle operations", async () => {
    document.cookie = "mobius_session_csrf=agent-studio-csrf";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(agent), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      agentStudioApi.lifecycle(ids.workspace, ids.canvas, ids.agent, "suspend"),
    ).resolves.toEqual(agent);

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(
      `http://localhost:8000/api/v1/workspaces/${ids.workspace}/canvases/${ids.canvas}/agent-studio/agents/${ids.agent}/lifecycle`,
    );
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toMatchObject({
      "Content-Type": "application/json",
      "X-CSRF-Token": "agent-studio-csrf",
    });
    expect(JSON.parse(String(init?.body))).toEqual({
      operation: "suspend",
      reasonCode: "human_suspend",
    });
  });

  it("allowlist-serializes authority-injected server fields", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          ...agent,
          grant: { capability: "shell.execute" },
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    const result = await agentStudioApi.lifecycle(ids.workspace, ids.canvas, ids.agent, "suspend");
    expect(result).toEqual(agent);
    expect(result).not.toHaveProperty("grant");
  });
});
