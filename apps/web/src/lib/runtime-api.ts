/** Public endpoint only. Secrets never belong in this server-to-browser binding. */
export function validatedPublicApiUrl(value: string): string {
  const url = new URL(value);
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (
    (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname.replace(/\/$/, "") !== "/api/v1"
  ) {
    throw new Error("Public API URL must be an HTTPS API origin with /api/v1 and no credentials");
  }
  return url.toString().replace(/\/$/, "");
}

export function browserApiUrl(fallback: string): string {
  const configured =
    typeof document === "undefined" ? undefined : document.documentElement.dataset.apiBaseUrl;
  return validatedPublicApiUrl(configured || fallback);
}
