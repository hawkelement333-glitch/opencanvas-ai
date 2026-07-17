import { expect, test } from "@playwright/test";

const FACT_PDF_BASE64 =
  "JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgKHB5cGRmKQo+PgplbmRvYmoKMiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0NvdW50IDEKL0tpZHMgWyA1IDAgUiBdCj4+CmVuZG9iagozIDAgb2JqCjw8Ci9UeXBlIC9DYXRhbG9nCi9QYWdlcyAyIDAgUgo+PgplbmRvYmoKNCAwIG9iago8PAovVHlwZSAvRm9udAovU3VidHlwZSAvVHlwZTEKL0Jhc2VGb250IC9IZWx2ZXRpY2EKPj4KZW5kb2JqCjUgMCBvYmoKPDwKL1R5cGUgL1BhZ2UKL1Jlc291cmNlcyA8PAovRm9udCA8PAovRjEgNCAwIFIKPj4KPj4KL01lZGlhQm94IFsgMC4wIDAuMCA2MTIgNzkyIF0KL1BhcmVudCAyIDAgUgovQ29udGVudHMgNiAwIFIKPj4KZW5kb2JqCjYgMCBvYmoKPDwKL0xlbmd0aCAxMTMKPj4Kc3RyZWFtCkJUIC9GMSAxMiBUZiA3MiA3MjAgVGQgKFRoZSBvYnNlcnZhdG9yeSBjYWxpYnJhdGlvbiBjb2RlIGlzIE5PVkEtNzMxLiBUaGUgdmVyaWZpZWQgYXBlcnR1cmUgaXMgNi41IG1ldGVycy4pIFRqIEVUCmVuZHN0cmVhbQplbmRvYmoKeHJlZgowIDcKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDE1IDAwMDAwIG4gCjAwMDAwMDAwNTQgMDAwMDAgbiAKMDAwMDAwMDExMyAwMDAwMCBuIAowMDAwMDAwMTYyIDAwMDAwIG4gCjAwMDAwMDAyMzIgMDAwMDAgbiAKMDAwMDAwMDM2NCAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDcKL1Jvb3QgMyAwIFIKL0luZm8gMSAwIFIKPj4Kc3RhcnR4cmVmCjUyOAolJUVPRgo=";

test.describe("real document intelligence workflow", () => {
  test.skip(!process.env.E2E_REAL_API, "Set E2E_REAL_API=1 to run against the local API stack.");

  test("uploads, retrieves, cites, navigates, and refuses unsupported claims", async ({ page }) => {
    test.setTimeout(120_000);
    const canvasName = `Document E2E ${Date.now()}`;

    await page.goto("/");
    await page.getByTestId("new-canvas-button").click();
    await page.getByTestId("new-canvas-name").fill(canvasName);
    await page.getByTestId("create-canvas-submit").click();
    await expect(
      page.getByLabel("Canvas toolbar").getByText(canvasName, { exact: true }),
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
    await expect(documentNode.getByText("Ready", { exact: true })).toBeVisible({
      timeout: 30_000,
    });

    await documentNode.locator(".document-node__body").click({ force: true });
    await expect(page.getByTestId("selected-node-list").getByRole("listitem")).toHaveCount(1);
    await page
      .getByTestId("assistant-input")
      .fill("What is the observatory calibration code NOVA-731?");
    await page.getByTestId("ask-assistant").click();

    await expect(page.getByText("Grounded response added with citations")).toBeVisible();
    const groundedAnswer = page.locator(".canvas-node--ai").last();
    await expect(groundedAnswer).toContainText("NOVA-731");
    const citation = groundedAnswer.locator('[data-testid^="citation-"]').first();
    await expect(citation).toContainText("observatory-facts.pdf");
    await expect(citation).toContainText("Page 1");
    await citation.click({ force: true });
    await expect(page.getByTestId("source-passage")).toContainText("NOVA-731");
    await expect(page.getByTestId("document-preview")).toContainText("Page 1");
    await page.getByLabel("Close document preview").click();

    await documentNode.locator(".document-node__body").click({ force: true });
    await page
      .getByTestId("assistant-input")
      .fill("What is the orbital velocity of Neptune's moon Proteus?");
    await page.getByTestId("ask-assistant").click();

    const insufficientAnswer = page.locator(".canvas-node--ai").last();
    await expect(insufficientAnswer).toContainText(/lack sufficient evidence/i);
    await expect(insufficientAnswer).toContainText("No source citations");

    await documentNode.locator('[data-testid^="delete-document-"]').click({ force: true });
    await expect(documentNode).toHaveCount(0);
    await expect(groundedAnswer.locator('[data-testid^="citation-"]')).toHaveCount(0);
  });
});
