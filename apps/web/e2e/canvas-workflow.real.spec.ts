import { expect, test } from "@playwright/test";

test.describe("real FastAPI + PostgreSQL workflow", () => {
  test.skip(!process.env.E2E_REAL_API, "Set E2E_REAL_API=1 to run against the local API stack.");

  test("persists a connected graph and an editable AI response across reloads", async ({
    page,
  }) => {
    const canvasName = `E2E canvas ${Date.now()}`;
    await page.goto("/");

    await page.getByTestId("new-canvas-button").click();
    await page.getByTestId("new-canvas-name").fill(canvasName);
    await page.getByTestId("create-canvas-submit").click();
    await expect(
      page.getByLabel("Canvas toolbar").getByText(canvasName, { exact: true }),
    ).toBeVisible();

    await page.getByTestId("add-note").click();
    let cards = page.locator('[data-testid^="canvas-node-"]');
    await expect(cards).toHaveCount(1);
    const first = cards.nth(0);
    await first.locator('input[aria-label="Node title"]').fill("Source insight");
    await first.locator("textarea").fill("Customers need context to remain visible.");

    await page.getByTestId("add-note").click();
    cards = page.locator('[data-testid^="canvas-node-"]');
    await expect(cards).toHaveCount(2);
    const second = cards.nth(1);
    await second.locator('input[aria-label="Node title"]').fill("Product response");
    await second.locator("textarea").fill("A connected canvas keeps reasoning inspectable.");

    await first.locator(".canvas-node__header").click();
    await second.locator(".canvas-node__header").click({ modifiers: ["Shift"] });
    await expect(page.getByTestId("selected-node-list").getByRole("listitem")).toHaveCount(2);
    const edgeCreated = page.waitForResponse(
      (response) => response.url().endsWith("/edges") && response.request().method() === "POST",
    );
    await page.getByTestId("connect-selected").click();
    expect((await edgeCreated).status()).toBe(201);
    await expect(page.locator(".react-flow__edge")).toHaveCount(1);
    await page.getByTestId("save-canvas").click();
    await expect(page.getByText("Saved", { exact: true })).toBeVisible();

    await page.reload();
    await expect(page.getByLabel("Source insight content")).toHaveValue(
      "Customers need context to remain visible.",
    );
    await expect(page.getByLabel("Product response content")).toHaveValue(
      "A connected canvas keeps reasoning inspectable.",
    );
    await expect(page.locator(".react-flow__edge")).toHaveCount(1);

    cards = page.locator('[data-testid^="canvas-node-"]');
    await cards.nth(0).locator(".canvas-node__header").click();
    await cards
      .nth(1)
      .locator(".canvas-node__header")
      .click({ modifiers: ["Shift"] });
    await page
      .getByTestId("assistant-input")
      .fill("Synthesize a product opportunity from these two notes.");
    await page.getByTestId("ask-assistant").click();
    const aiCard = page.locator(".canvas-node--ai");
    await expect(aiCard).toBeVisible();
    await aiCard.locator("textarea").fill("Edited AI synthesis persisted by the real stack.");
    await page.getByTestId("save-canvas").click();
    await expect(page.getByText("Saved", { exact: true })).toBeVisible();

    await page.reload();
    await expect(page.locator(".canvas-node--ai textarea")).toHaveValue(
      "Edited AI synthesis persisted by the real stack.",
    );
  });
});
