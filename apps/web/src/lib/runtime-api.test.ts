import { afterEach, describe, expect, it } from "vitest";
import { browserApiUrl, validatedPublicApiUrl } from "./runtime-api";

afterEach(() => {
  delete document.documentElement.dataset.apiBaseUrl;
});
describe("public runtime API binding", () => {
  it("uses the deployed origin without rebuilding or proxying requests", () => {
    document.documentElement.dataset.apiBaseUrl = "https://api.deployment.example/api/v1";
    expect(browserApiUrl("http://localhost:8000/api/v1")).toBe(
      "https://api.deployment.example/api/v1",
    );
  });
  it("preserves the local fallback", () => {
    expect(browserApiUrl("http://127.0.0.1:8000/api/v1/")).toBe("http://127.0.0.1:8000/api/v1");
  });
  it.each([
    "https://user:secret@api.example/api/v1",
    "http://remote.example/api/v1",
    "https://api.example/api/v1?token=private",
    "https://api.example/api/v1#private",
    "https://api.example/wrong",
    "javascript:alert(1)",
  ])("rejects unsafe public binding %s", (url) => {
    expect(() => validatedPublicApiUrl(url)).toThrow();
  });
});
