import { randomUUID } from "node:crypto";

import { expect, test as base } from "@playwright/test";

// Use real session cookies and CSRF handling against an isolated local API.
// Each scenario owns its account/workspace; no browser responses are intercepted.
export const test = base.extend({
  page: async ({ page }, providePage) => {
    const api = new URL(process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000/api/v1");
    if (
      api.protocol !== "http:" ||
      !["127.0.0.1", "localhost", "[::1]"].includes(api.hostname) ||
      api.username ||
      api.password
    ) {
      throw new Error("Real-stack fixtures require an isolated loopback HTTP API.");
    }
    const identity = randomUUID();
    const response = await page.request.post(`${api.href.replace(/\/$/, "")}/auth/signup`, {
      data: {
        email: `browser-${identity}@mobius.invalid`,
        password: `Local-browser-${randomUUID()}!`,
        displayName: "Synthetic browser fixture",
      },
    });
    expect(response.status(), "The real API must create the isolated fixture account").toBe(201);
    await providePage(page);
  },
});

export { expect };
