import { expect, test } from "./real-api-fixture";

const FACT_PDF_BASE64 =
  "JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgKHB5cGRmKQo+PgplbmRvYmoKMiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0NvdW50IDEKL0tpZHMgWyA1IDAgUiBdCj4+CmVuZG9iagozIDAgb2JqCjw8Ci9UeXBlIC9DYXRhbG9nCi9QYWdlcyAyIDAgUgo+PgplbmRvYmoKNCAwIG9iago8PAovVHlwZSAvRm9udAovU3VidHlwZSAvVHlwZTEKL0Jhc2VGb250IC9IZWx2ZXRpY2EKPj4KZW5kb2JqCjUgMCBvYmoKPDwKL1R5cGUgL1BhZ2UKL1Jlc291cmNlcyA8PAovRm9udCA8PAovRjEgNCAwIFIKPj4KPj4KL01lZGlhQm94IFsgMC4wIDAuMCA2MTIgNzkyIF0KL1BhcmVudCAyIDAgUgovQ29udGVudHMgNiAwIFIKPj4KZW5kb2JqCjYgMCBvYmoKPDwKL0xlbmd0aCAxMTMKPj4Kc3RyZWFtCkJUIC9GMSAxMiBUZiA3MiA3MjAgVGQgKFRoZSBvYnNlcnZhdG9yeSBjYWxpYnJhdGlvbiBjb2RlIGlzIE5PVkEtNzMxLiBUaGUgdmVyaWZpZWQgYXBlcnR1cmUgaXMgNi41IG1ldGVycy4pIFRqIEVUCmVuZHN0cmVhbQplbmRvYmoKeHJlZgowIDcKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDE1IDAwMDAwIG4gCjAwMDAwMDAwNTQgMDAwMDAgbiAKMDAwMDAwMDExMyAwMDAwMCBuIAowMDAwMDAwMTYyIDAwMDAwIG4gCjAwMDAwMDAyMzIgMDAwMDAgbiAKMDAwMDAwMDM2NCAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDcKL1Jvb3QgMyAwIFIKL0luZm8gMSAwIFIKPj4Kc3RhcnR4cmVmCjUyOAolJUVPRgo=";

test.describe("real document intelligence workflow", () => {
  test.skip(!process.env.E2E_REAL_API, "Set E2E_REAL_API=1 to run against the local API stack.");

  test("uploads, retrieves, cites, navigates, and refuses unsupported claims", async ({ page }) => {
    test.setTimeout(120_000);
    const securePilot = process.env.E2E_SECURE_PILOT === "1";
    const canvasName = `Document E2E ${Date.now()}`;

    await page.goto("/");
    await page.getByTestId("new-canvas-button").click();
    await page.getByTestId("new-canvas-name").fill(canvasName);
    await page.getByTestId("create-canvas-submit").click();
    await expect(
      page.getByRole("navigation", { name: "Canvases" }).getByRole("button", {
        name: `Solar System · ${canvasName}`,
        exact: true,
      }),
    ).toBeVisible();

    await page.getByTestId("document-file-input").setInputFiles({
      name: "observatory-facts.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from(FACT_PDF_BASE64, "base64"),
    });

    const documentNode = page
      .locator("article.document-node")
      .filter({ hasText: "observatory-facts.pdf" });
    await expect(documentNode).toBeVisible();
    await expect(
      documentNode.getByRole("status").filter({ hasText: /^Ready source$/ }),
    ).toBeVisible({
      timeout: 30_000,
    });

    await documentNode.locator(".canvas-node__header").click();
    await expect(page.getByTestId("selected-node-list").getByRole("listitem")).toHaveCount(1);
    await expect(page.getByTestId("controlled-draft-input")).toBeVisible();
    await page
      .getByTestId("controlled-draft-input")
      .fill("What is the observatory calibration code NOVA-731?");
    await page.getByTestId("start-controlled-draft").click();

    await expect(page.getByText("Grounded draft confirmed by the server")).toBeVisible();
    await expect(page.locator(".canvas-node--ai")).toHaveCount(0);
    const groundedSave = page.waitForResponse((response) =>
      /\/agent-executions\/[^/]+\/artifact$/.test(response.url()),
    );
    await page.getByTestId("save-draft-artifact").click();
    await expect(page.getByText("Saved as an editable canvas artifact")).toBeVisible();
    const groundedId = ((await (await groundedSave).json()) as { id: string }).id;
    const groundedAnswer = page.getByTestId(`canvas-node-${groundedId}`);
    await expect(groundedAnswer.locator("textarea")).toHaveValue(/NOVA-731/);
    await groundedAnswer.getByText("Original AI evidence").click();
    const citation = groundedAnswer.locator('[data-testid^="citation-"]').first();
    await expect(citation).toContainText("observatory-facts.pdf");
    await expect(citation).toContainText("Page 1");
    await citation.click({ force: true });
    await expect(page.getByTestId("source-passage")).toContainText("NOVA-731");
    await expect(page.getByTestId("document-preview")).toContainText("Page 1");
    await page.getByLabel("Close document preview").click();

    await documentNode.locator(".document-node__body").click({ force: true });
    await page
      .getByTestId("controlled-draft-input")
      .fill("What is the orbital velocity of Neptune's moon Proteus?");
    await page.getByTestId("start-controlled-draft").click();

    await expect(page.getByText("Insufficient evidence in the selected context")).toBeVisible();
    await expect(page.locator(".canvas-node--ai")).toHaveCount(1);
    const refusalSave = page.waitForResponse((response) =>
      /\/agent-executions\/[^/]+\/artifact$/.test(response.url()),
    );
    await page.getByTestId("save-draft-artifact").click();
    await expect(page.getByText("Saved as an editable canvas artifact")).toBeVisible();
    const refusalId = ((await (await refusalSave).json()) as { id: string }).id;
    const insufficientAnswer = page.getByTestId(`canvas-node-${refusalId}`);
    await insufficientAnswer.getByText("Original AI evidence").click();
    await expect(insufficientAnswer).toContainText(
      /lack sufficient evidence|do not contain sufficient evidence/i,
    );
    await expect(insufficientAnswer).toContainText("No source citations");

    await documentNode.locator('[data-testid^="delete-document-"]').click({ force: true });
    if (securePilot) {
      await expect(documentNode).toContainText("Deletion requested");
      await expect(documentNode.getByRole("button", { name: /preview/i })).toBeDisabled();
    } else {
      await expect(documentNode).toHaveCount(0);
    }
    await page.reload();
    await expect(groundedAnswer.locator('[data-testid^="citation-"]')).toHaveCount(0);
  });
});
