import { expect, test } from "./real-api-fixture";

const FACT_PDF_BASE64 =
  "JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgKHB5cGRmKQo+PgplbmRvYmoKMiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0NvdW50IDEKL0tpZHMgWyA1IDAgUiBdCj4+CmVuZG9iagozIDAgb2JqCjw8Ci9UeXBlIC9DYXRhbG9nCi9QYWdlcyAyIDAgUgo+PgplbmRvYmoKNCAwIG9iago8PAovVHlwZSAvRm9udAovU3VidHlwZSAvVHlwZTEKL0Jhc2VGb250IC9IZWx2ZXRpY2EKPj4KZW5kb2JqCjUgMCBvYmoKPDwKL1R5cGUgL1BhZ2UKL1Jlc291cmNlcyA8PAovRm9udCA8PAovRjEgNCAwIFIKPj4KPj4KL01lZGlhQm94IFsgMC4wIDAuMCA2MTIgNzkyIF0KL1BhcmVudCAyIDAgUgovQ29udGVudHMgNiAwIFIKPj4KZW5kb2JqCjYgMCBvYmoKPDwKL0xlbmd0aCAxMTMKPj4Kc3RyZWFtCkJUIC9GMSAxMiBUZiA3MiA3MjAgVGQgKFRoZSBvYnNlcnZhdG9yeSBjYWxpYnJhdGlvbiBjb2RlIGlzIE5PVkEtNzMxLiBUaGUgdmVyaWZpZWQgYXBlcnR1cmUgaXMgNi41IG1ldGVycy4pIFRqIEVUCmVuZHN0cmVhbQplbmRvYmoKeHJlZgowIDcKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDE1IDAwMDAwIG4gCjAwMDAwMDAwNTQgMDAwMDAgbiAKMDAwMDAwMDExMyAwMDAwMCBuIAowMDAwMDAwMTYyIDAwMDAwIG4gCjAwMDAwMDAyMzIgMDAwMDAgbiAKMDAwMDAwMDM2NCAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDcKL1Jvb3QgMyAwIFIKL0luZm8gMSAwIFIKPj4Kc3RhcnR4cmVmCjUyOAolJUVPRgo=";

// Generation is read-only; an explicit save creates an editable derivative with immutable provenance.
test.describe("real core document and controlled grounded-draft workflow", () => {
  test.skip(!process.env.E2E_REAL_API, "Set E2E_REAL_API=1 to use the isolated local API stack.");

  test("uploads a real PDF, retrieves an exact citation, refuses unsupported claims, and fences deleted evidence", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    const securePilot = process.env.E2E_SECURE_PILOT === "1";
    const canvasName = `Controlled document E2E ${Date.now()}`;
    const apiBase = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000/api/v1").replace(
      /\/$/,
      "",
    );

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
    if (securePilot) {
      await expect(documentNode).toContainText(/quarantine|scanning/i);
      await page.reload();
      await expect(documentNode).toBeVisible();
    }
    await expect(
      documentNode.getByRole("status").filter({ hasText: /^Ready source$/ }),
    ).toBeVisible({
      timeout: 30_000,
    });
    await documentNode.locator(".canvas-node__header").click();
    await expect(page.getByTestId("selected-node-list").getByRole("listitem")).toHaveCount(1);

    const prepareResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/agent-executions/drafts/prepare") &&
        response.request().method() === "POST",
    );
    const groundedResponse = page.waitForResponse((response) =>
      /\/agent-executions\/[^/]+\/run$/.test(response.url()),
    );
    await page
      .getByTestId("controlled-draft-input")
      .fill("What is the observatory calibration code NOVA-731?");
    await page.getByTestId("start-controlled-draft").click();
    const prepared = await prepareResponse;
    expect(prepared.status()).toBe(201);
    const { canvasId } = prepared.request().postDataJSON() as { canvasId: string };
    const grounded = await groundedResponse;
    expect(grounded.status()).toBe(200);
    const answer = (await grounded.json()) as {
      text: string;
      traceId: string;
      executionId: string;
      insufficientEvidence: boolean;
      citations: Array<{
        documentId: string;
        documentVersion: number;
        chunkId: string;
        quote: string;
      }>;
    };
    expect(answer.insufficientEvidence).toBe(false);
    expect(answer.text).toContain("NOVA-731");
    expect(answer.citations).toHaveLength(1);
    const citation = answer.citations[0];
    if (!citation) throw new Error("Grounded answer must contain its exact citation");
    expect(citation.documentVersion).toBeGreaterThanOrEqual(0);
    expect(citation.quote).toContain("NOVA-731");
    await expect(page.getByTestId("controlled-draft-result")).toContainText("NOVA-731");
    await expect(page.getByText("Grounded draft confirmed by the server")).toBeVisible();
    await expect(
      page.getByRole("list", { name: "Validated citations" }).getByRole("listitem"),
    ).toHaveCount(1);

    const passagePath = `/documents/${citation.documentId}/chunks/${citation.chunkId}`;
    const passageResponse = page.waitForResponse((response) =>
      response.url().endsWith(passagePath),
    );
    await page.getByRole("button", { name: "Citation [1]", exact: true }).click();
    const passage = await passageResponse;
    expect(passage.status()).toBe(200);
    expect(await passage.json()).toMatchObject({
      documentId: citation.documentId,
      chunkId: citation.chunkId,
      pageNumber: 1,
      documentTitle: "observatory-facts.pdf",
    });
    await expect(page.getByTestId("source-passage")).toContainText("NOVA-731");
    await expect(page.getByTestId("source-passage")).toContainText("Page 1");
    await expect(page.getByTestId("document-preview")).toContainText("observatory-facts.pdf");
    await page.getByLabel("Close document preview").click();

    await expect(page.locator(".canvas-node--ai")).toHaveCount(0);
    const artifactResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/agent-executions/${answer.executionId}/artifact`),
    );
    await page.getByTestId("save-draft-artifact").click();
    const saveResponse = await artifactResponse;
    expect(saveResponse.ok()).toBe(true);
    const artifact = (await saveResponse.json()) as { id: string };
    const artifactCard = page.getByTestId(`canvas-node-${artifact.id}`);
    await expect(artifactCard).toBeVisible();
    await expect(artifactCard.locator("textarea")).toHaveValue(answer.text);
    await artifactCard.locator("textarea").fill("User-edited observatory summary.");
    await page.getByTestId("save-canvas").click();
    await expect(page.getByText("Saved", { exact: true })).toBeVisible();
    await page.reload();
    await expect(artifactCard.locator("textarea")).toHaveValue("User-edited observatory summary.");
    await expect(artifactCard).toContainText("User-edited content � original evidence unchanged");
    await artifactCard.getByText("Original AI evidence").click();
    await expect(artifactCard.getByTestId("draft-original-text")).toHaveText(answer.text);
    await expect(
      artifactCard.getByRole("link", { name: "Inspect original Trace" }),
    ).toHaveAttribute("href", new RegExp(answer.traceId));
    await artifactCard
      .getByRole("button", { name: "Open source 1: observatory-facts.pdf" })
      .click({ force: true });
    await expect(page.getByTestId("source-passage")).toContainText("NOVA-731");
    await page.getByLabel("Close document preview").click();

    const csrfName = process.env.NEXT_PUBLIC_CSRF_COOKIE_NAME ?? "mobius_session_csrf";
    const csrf = (await page.context().cookies(apiBase)).find((cookie) => cookie.name === csrfName);
    expect(csrf, "The real authenticated search must use the issued CSRF token").toBeDefined();
    const searchRequest = {
      headers: { "X-CSRF-Token": decodeURIComponent(csrf!.value) },
      data: {
        query: "What is the observatory calibration code NOVA-731?",
        documentIds: [citation.documentId],
      },
    };
    const searchPath = `${apiBase}/canvases/${canvasId}/documents/search`;
    const beforeDeletion = await page.request.post(searchPath, searchRequest);
    expect(beforeDeletion.status()).toBe(200);
    const search = (await beforeDeletion.json()) as {
      matches: Array<{ documentId: string; chunkId: string; text: string }>;
      insufficientContext: boolean;
    };
    expect(search.insufficientContext).toBe(false);
    expect(search.matches).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          documentId: citation.documentId,
          chunkId: citation.chunkId,
          text: expect.stringContaining("NOVA-731"),
        }),
      ]),
    );

    const refusalResponse = page.waitForResponse((response) =>
      /\/agent-executions\/[^/]+\/run$/.test(response.url()),
    );
    await documentNode.locator(".canvas-node__header").click();
    await page
      .getByTestId("controlled-draft-input")
      .fill("What is the orbital velocity of Neptune's moon Proteus?");
    await page.getByTestId("start-controlled-draft").click();
    const refusal = await refusalResponse;
    expect(refusal.status()).toBe(200);
    expect(await refusal.json()).toMatchObject({ insufficientEvidence: true, citations: [] });
    await expect(page.getByTestId("controlled-draft-result")).toContainText(
      /lack sufficient evidence|do not contain sufficient evidence/i,
    );
    await expect(page.getByText("Insufficient evidence in the selected context")).toBeVisible();
    await expect(page.getByRole("list", { name: "Validated citations" })).toHaveCount(0);
    // A second generation must not materialize another artifact without explicit saving.
    await expect(page.locator(".canvas-node--ai")).toHaveCount(1);

    const deletionResponse = page.waitForResponse((response) =>
      securePilot
        ? response.url().endsWith("/deletion-requests") && response.request().method() === "POST"
        : response.url().endsWith(`/documents/${citation.documentId}`) &&
          response.request().method() === "DELETE",
    );
    await documentNode.locator('[data-testid^="delete-document-"]').click();
    expect((await deletionResponse).status()).toBe(securePilot ? 200 : 204);
    if (securePilot) {
      await expect(documentNode).toContainText("Deletion requested", { timeout: 15_000 });
    } else {
      await expect(documentNode).toHaveCount(0);
      expect((await page.request.get(`${apiBase}/documents/${citation.documentId}`)).status()).toBe(
        404,
      );
    }
    expect((await page.request.get(`${apiBase}${passagePath}`)).status()).toBe(404);
    const afterDeletion = await page.request.post(searchPath, searchRequest);
    if (securePilot) {
      expect(afterDeletion.status()).toBe(200);
      expect(await afterDeletion.json()).toMatchObject({ matches: [], insufficientContext: true });
    } else {
      expect(afterDeletion.status()).toBe(400);
      expect(await afterDeletion.json()).toMatchObject({ code: "invalid_selected_documents" });
    }
    await page.reload();
    await expect(artifactCard.locator("textarea")).toHaveValue("User-edited observatory summary.");
    await artifactCard.getByText("Original AI evidence").click();
    await expect(artifactCard.getByTestId("draft-original-text")).toHaveText(answer.text);
    await expect(artifactCard.locator('[data-testid^="citation-"]')).toHaveCount(0);
    if (securePilot) {
      await expect
        .poll(
          async () => {
            const status = await page.request.get(
              `${apiBase}/documents/${citation.documentId}/upload-session`,
            );
            expect(status.status()).toBe(200);
            const { objectState } = await status.json();
            expect(["deletion_requested", "deleted"]).toContain(objectState);
            if (objectState === "deleted") return (await documentNode.count()) === 0;
            if ((await documentNode.count()) !== 1) return false;
            return (
              (await documentNode.textContent())?.includes("Deletion requested") &&
              (await documentNode.getByRole("button", { name: /preview/i }).isDisabled())
            );
          },
          { timeout: 15_000 },
        )
        .toBe(true);
    } else {
      await expect(documentNode).toHaveCount(0);
    }
  });
});
