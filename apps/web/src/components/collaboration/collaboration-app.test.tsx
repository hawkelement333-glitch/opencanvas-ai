import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CollaborationApp } from "./collaboration-app";

const replace = vi.fn();
const context = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

vi.mock("@/lib/api-client", () => ({
  APIError: class APIError extends Error {
    status = 500;
    code = "api_error";
  },
  accountApi: {
    me: vi.fn().mockResolvedValue({
      id: "00000000-0000-4000-8000-000000000001",
      email: "member@example.test",
      displayName: "Member",
      emailVerified: true,
    }),
  },
  workspaceApi: {
    list: vi.fn().mockResolvedValue([
      {
        id: "00000000-0000-4000-8000-000000000010",
        name: "Atlas",
        description: null,
        ownerId: "00000000-0000-4000-8000-000000000001",
        version: 1,
        lifecycleState: "active",
        metadata: {},
        legacyCanvasId: null,
        createdAt: "2026-07-26T12:00:00Z",
        updatedAt: "2026-07-26T12:00:00Z",
      },
      {
        id: "00000000-0000-4000-8000-000000000020",
        name: "Orion",
        description: null,
        ownerId: "00000000-0000-4000-8000-000000000009",
        version: 1,
        lifecycleState: "active",
        metadata: {},
        legacyCanvasId: null,
        createdAt: "2026-07-26T12:00:00Z",
        updatedAt: "2026-07-26T12:00:00Z",
      },
    ]),
  },
  canvasApi: { listCanvases: vi.fn().mockResolvedValue([]) },
  collaborationApi: {
    context: (...args: unknown[]) => context(...args),
    memberships: vi.fn().mockResolvedValue([]),
    invitations: vi.fn().mockResolvedValue([]),
    approvalAuthorities: vi.fn().mockResolvedValue([]),
    shares: vi.fn().mockResolvedValue([]),
    ownershipTransfers: vi.fn().mockResolvedValue([]),
    activity: vi.fn().mockResolvedValue([]),
    comments: vi.fn().mockResolvedValue([]),
    workflows: vi.fn().mockResolvedValue([]),
    agents: vi.fn().mockResolvedValue([]),
  },
}));

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false, gcTime: 0 } },
        })
      }
    >
      {children}
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  context.mockImplementation((workspaceId: string) =>
    Promise.resolve({
      workspaceId,
      workspaceName: workspaceId.endsWith("20") ? "Orion" : "Atlas",
      workspaceLifecycleState: "active",
      workspaceOwnerUserId: "00000000-0000-4000-8000-000000000009",
      authenticatedUserId: "00000000-0000-4000-8000-000000000001",
      membershipId: "00000000-0000-4000-8000-000000000003",
      membershipState: "active",
      role: "viewer",
      authorityGeneration: workspaceId.endsWith("20") ? 8 : 7,
      permissionCeiling: [
        "workspace.view",
        "canvas.view",
        "resource.view",
        "workflow.view",
        "agent.view",
        "collaboration_activity.view",
        "trace.view",
        "evidence_bundle.view",
      ],
    }),
  );
});

describe("CollaborationApp", () => {
  it("shows only server-returned workspaces and confirmed authority", async () => {
    render(
      <Wrapper>
        <CollaborationApp initialWorkspaceId="00000000-0000-4000-8000-000000000010" />
      </Wrapper>,
    );

    expect(await screen.findByRole("heading", { name: "Collaboration" })).toBeInTheDocument();
    expect(await screen.findByText("Generation 7")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Authorized workspace" })).toHaveTextContent(
      "Atlas",
    );
    expect(screen.getByRole("combobox", { name: "Authorized workspace" })).toHaveTextContent(
      "Orion",
    );
    expect(screen.queryByText("Hidden workspace")).not.toBeInTheDocument();
  });

  it("switches workspace through a keyboard-operable native control and reconfirms authority", async () => {
    const user = userEvent.setup();
    render(
      <Wrapper>
        <CollaborationApp initialWorkspaceId="00000000-0000-4000-8000-000000000010" />
      </Wrapper>,
    );
    const switcher = await screen.findByRole("combobox", { name: "Authorized workspace" });
    await user.selectOptions(switcher, "00000000-0000-4000-8000-000000000020");

    await waitFor(() =>
      expect(context).toHaveBeenCalledWith(
        "00000000-0000-4000-8000-000000000020",
        expect.any(AbortSignal),
      ),
    );
    expect(await screen.findByText("Generation 8")).toBeInTheDocument();
    expect(replace).toHaveBeenLastCalledWith(
      "/collaboration?workspaceId=00000000-0000-4000-8000-000000000020",
    );
  });

  it("does not load or display administration controls for a viewer", async () => {
    const user = userEvent.setup();
    render(
      <Wrapper>
        <CollaborationApp initialWorkspaceId="00000000-0000-4000-8000-000000000010" />
      </Wrapper>,
    );
    await screen.findByText("Generation 7");
    await user.click(screen.getByRole("tab", { name: "People" }));
    expect(
      screen.getByText("Member administration is not available to your current membership."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create invitation" })).not.toBeInTheDocument();
  });

  it("exposes semantic tabs, landmarks, and a live mutation region", async () => {
    const user = userEvent.setup();
    render(
      <Wrapper>
        <CollaborationApp initialWorkspaceId="00000000-0000-4000-8000-000000000010" />
      </Wrapper>,
    );
    await screen.findByText("Generation 7");
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "Collaboration areas" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(5);
    expect(document.querySelector('[aria-live="polite"]')).toBeInTheDocument();
    const overview = screen.getByRole("tab", { name: "Overview" });
    overview.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "People" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "People" })).toHaveAttribute("aria-selected", "true");
  });
});
