// @vitest-environment node
import { describe, it, expect, vi, afterEach } from "vitest";
import { allowedRoute, limitedBody, sameOrigin } from "@/lib/gateway";
import { backendUrl } from "@/lib/config";
afterEach(() => vi.unstubAllEnvs());
describe("gateway boundary", () => {
  it("does not expose platform administration or arbitrary proxy paths", () => {
    for (const path of [
      "ingest",
      "metrics",
      "health",
      "../query",
      "workspaces/../../metrics",
      "https://evil.test",
    ])
      expect(allowedRoute(path, "POST")).toBe(false);
    expect(allowedRoute("workspaces", "GET")).toBe(true);
  });
  it("requires same-origin browser mutations", () => {
    expect(
      sameOrigin(
        new Request("https://site.test/api/demo", {
          method: "POST",
          headers: { origin: "https://evil.test" },
        }),
      ),
    ).toBe(false);
    expect(
      sameOrigin(
        new Request("https://site.test/api/demo", {
          method: "POST",
          headers: { origin: "https://site.test" },
        }),
      ),
    ).toBe(true);
    expect(
      sameOrigin(new Request("https://site.test/api/demo", { method: "POST" })),
    ).toBe(false);
  });
  it("checks the browser Host when Next.js normalizes its internal URL", () => {
    expect(
      sameOrigin(
        new Request("http://localhost:3000/api/demo", {
          method: "POST",
          headers: { host: "127.0.0.1:3000", origin: "http://127.0.0.1:3000" },
        }),
      ),
    ).toBe(true);
    expect(
      sameOrigin(
        new Request("https://site.test/api/demo", {
          method: "POST",
          headers: {
            host: "site.test",
            origin: "https://evil.test",
            "x-forwarded-host": "evil.test",
          },
        }),
      ),
    ).toBe(false);
  });
  it("uses only the configured HTTPS backend", () => {
    vi.stubEnv("RAG_API_URL", "https://api.test/");
    expect(backendUrl("workspaces")?.href).toBe("https://api.test/workspaces");
    vi.stubEnv("RAG_API_URL", "http://evil.test");
    expect(() => backendUrl("workspaces")).toThrow();
    vi.stubEnv("RAG_API_URL", "https://user:password@api.test");
    expect(() => backendUrl("workspaces")).toThrow();
  });
  it("rejects oversized bodies even without a length header", async () => {
    const request = new Request("https://site.test", {
      method: "POST",
      body: "a".repeat(2000),
    });
    await expect(limitedBody(request, 100)).rejects.toThrow("BODY_TOO_LARGE");
  });
});
