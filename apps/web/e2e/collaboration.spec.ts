import { expect, test, type Page, type Route } from "@playwright/test";

const ids = {
  user: "10000000-0000-4000-8000-000000000001",
  firstWorkspace: "20000000-0000-4000-8000-000000000001",
  secondWorkspace: "20000000-0000-4000-8000-000000000002",
  membership: "30000000-0000-4000-8000-000000000001",
};
const timestamp = "2026-07-26T18:00:00Z";

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

async function installCollaborationApi(page: Page): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api\/v1/, "");
    if (path === "/auth/me") {
      await json(route, {
        id: ids.user,
        email: "viewer@example.test",
        displayName: "Viewer",
        emailVerified: true,
      });
    } else if (path === "/workspaces") {
      await json(
        route,
        [ids.firstWorkspace, ids.secondWorkspace].map((id, index) => ({
          id,
          name: index === 0 ? "Atlas" : "Orion",
          description: null,
          ownerId: ids.user,
          version: 1,
          lifecycleState: "active",
          metadata: {},
          legacyCanvasId: null,
          createdAt: timestamp,
          updatedAt: timestamp,
        })),
      );
    } else if (path.endsWith("/collaboration-context")) {
      const workspaceId = path.split("/")[2]!;
      await json(route, {
        workspaceId,
        workspaceName: workspaceId === ids.firstWorkspace ? "Atlas" : "Orion",
        workspaceLifecycleState: "active",
        workspaceOwnerUserId: ids.user,
        authenticatedUserId: ids.user,
        membershipId: ids.membership,
        membershipState: "active",
        role: "viewer",
        authorityGeneration: workspaceId === ids.firstWorkspace ? 7 : 8,
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
      });
    } else if (path.endsWith("/collaboration-activity")) {
      await json(route, []);
    } else {
      await json(route, { detail: "Not available in this bounded smoke test." }, 404);
    }
  });
}

test("workspace switching is keyboard-operable and refreshes server authority", async ({
  page,
}) => {
  await installCollaborationApi(page);
  await page.goto(`/collaboration?workspaceId=${ids.firstWorkspace}`);

  await expect(page.getByRole("heading", { name: "Collaboration" })).toBeVisible();
  await expect(page.getByText("Generation 7")).toBeVisible();
  const switcher = page.getByRole("combobox", { name: "Authorized workspace" });
  await switcher.focus();
  await switcher.press("ArrowDown");
  await switcher.press("Enter");

  await expect(page).toHaveURL(new RegExp(ids.secondWorkspace));
  await expect(page.getByText("Generation 8")).toBeVisible();
  await expect(page.getByText(/server authority is being confirmed/i)).toBeVisible();
});

test("mobile collaboration controls remain visible, wrapped, and semantic", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installCollaborationApi(page);
  await page.goto(`/collaboration?workspaceId=${ids.firstWorkspace}`);

  await expect(page.getByRole("tablist", { name: "Collaboration areas" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Overview" })).toBeVisible();
  await page.getByRole("tab", { name: "People" }).click();
  await expect(
    page.getByText("Member administration is not available to your current membership."),
  ).toBeVisible();
  expect(await page.locator("body").evaluate((body) => body.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
