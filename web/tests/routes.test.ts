// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const identity = vi.hoisted(() => ({ getToken: vi.fn(), auth: vi.fn() }));
vi.mock("@clerk/nextjs/server", () => ({ auth: identity.auth }));
import { POST as workspacePost, GET } from "@/app/api/[...path]/route";
import { POST as demoPost } from "@/app/api/demo/route";
const workspace = "ws_" + "a".repeat(32);
const context = (path: string[]) => ({ params: Promise.resolve({ path }) });
const request = (path: string, body: object, origin = "https://rag.example") =>
  new Request(`https://rag.example/api/${path}`, {
    method: "POST",
    headers: {
      Origin: origin,
      "Content-Type": "application/json",
      Authorization: "Bearer browser-forgery",
      "X-Workspace-ID": workspace,
    },
    body: JSON.stringify(body),
  });
beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "configured");
  vi.stubEnv("CLERK_SECRET_KEY", "server-only");
  vi.stubEnv("RAG_API_URL", "https://api.example");
  vi.stubEnv("DEMO_PROXY_SECRET", "demo-only");
  identity.auth.mockResolvedValue({
    userId: "signed-in",
    getToken: identity.getToken,
  });
  identity.getToken.mockResolvedValue("verified-server-token");
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});
describe("workspace gateway", () => {
  it("forwards the server token and workspace, never browser credentials", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response("{}", {
        headers: {
          "Content-Type": "application/json",
          "Set-Cookie": "private=secret",
        },
      }),
    );
    vi.stubGlobal("fetch", fetcher);
    const response = await workspacePost(
      request("session", {}),
      context(["session"]),
    );
    const [url, options] = fetcher.mock.calls[0];
    expect(url.toString()).toBe("https://api.example/session");
    expect(options.headers.get("Authorization")).toBe(
      "Bearer verified-server-token",
    );
    expect(options.headers.get("X-Workspace-ID")).toBe(workspace);
    expect(identity.getToken).toHaveBeenCalledWith({
      template: "production-rag",
    });
    expect(response.headers.get("Set-Cookie")).toBeNull();
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });
  it("rejects cross-origin writes and privileged routes before authentication", async () => {
    expect(
      (
        await workspacePost(
          request("workspaces", { name: "x" }, "https://evil.example"),
          context(["workspaces"]),
        )
      ).status,
    ).toBe(403);
    expect(
      (
        await GET(
          new Request("https://rag.example/api/metrics"),
          context(["metrics"]),
        )
      ).status,
    ).toBe(404);
    expect(identity.auth).not.toHaveBeenCalled();
  });
  it("fails closed without login configuration or a signed-in user", async () => {
    vi.stubEnv("CLERK_SECRET_KEY", "");
    expect(
      (
        await GET(
          new Request("https://rag.example/api/workspaces"),
          context(["workspaces"]),
        )
      ).status,
    ).toBe(503);
    vi.stubEnv("CLERK_SECRET_KEY", "configured");
    identity.auth.mockResolvedValue({ userId: null });
    expect(
      (
        await GET(
          new Request("https://rag.example/api/workspaces"),
          context(["workspaces"]),
        )
      ).status,
    ).toBe(401);
  });
});
describe("public demo gateway", () => {
  it("allows only the question and forwards a separate server credential", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response('{"answer":"public"}'));
    vi.stubGlobal("fetch", fetcher);
    expect(
      (await demoPost(request("demo", { query: "How?", corpus_id: "private" })))
        .status,
    ).toBe(400);
    expect(fetcher).not.toHaveBeenCalled();
    expect((await demoPost(request("demo", { query: "How?" }))).status).toBe(
      200,
    );
    const [url, options] = fetcher.mock.calls[0];
    expect(url.toString()).toBe("https://api.example/demo/query");
    expect(options.headers["X-Demo-Key"]).toBe("demo-only");
    expect(options.headers.Authorization).toBeUndefined();
    expect(options.body).toBe('{"query":"How?"}');
  });
  it("rejects cross-origin calls and oversized bodies without reaching inference", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect(
      (
        await demoPost(
          request("demo", { query: "How?" }, "https://evil.example"),
        )
      ).status,
    ).toBe(403);
    expect(
      (await demoPost(request("demo", { query: "a".repeat(9000) }))).status,
    ).toBe(413);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
