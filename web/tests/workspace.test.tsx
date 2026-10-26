import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WorkspaceApp } from "@/components/workspace";
const id = "ws_" + "a".repeat(32),
  user = "usr_" + "b".repeat(64);
afterEach(() => vi.unstubAllGlobals());
function backend(role: string) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      if (input === "/api/workspaces")
        return Response.json({
          user_id: user,
          workspaces: [{ id, name: "Design handbook", role }],
        });
      if (input.endsWith("/documents")) return Response.json([]);
      if (input.endsWith("/members"))
        return Response.json([{ user_id: user, role }]);
      return Response.json([]);
    }),
  );
}
describe("workspace interface", () => {
  it("shows member capabilities without admin controls", async () => {
    backend("member");
    render(<WorkspaceApp />);
    expect(
      await screen.findByRole("heading", { name: "Design handbook" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Members" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Documents/ }));
    expect(
      screen.queryByRole("button", { name: "Refresh source" }),
    ).not.toBeInTheDocument();
  });
  it("allows editors to refresh a source without managing members", async () => {
    backend("editor");
    render(<WorkspaceApp />);
    await screen.findByRole("heading", { name: "Design handbook" });
    fireEvent.click(screen.getByRole("button", { name: /Documents/ }));
    expect(
      screen.getByRole("button", { name: "Refresh source" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Members" }),
    ).not.toBeInTheDocument();
  });
  it("gives admins access to the membership interface", async () => {
    backend("admin");
    render(<WorkspaceApp />);
    await screen.findByRole("heading", { name: "Design handbook" });
    fireEvent.click(screen.getByRole("button", { name: "Members" }));
    expect(await screen.findByText(/People & permissions/)).toBeInTheDocument();
    expect(
      screen.getByLabelText("Add a teammate by workspace user ID"),
    ).toBeInTheDocument();
  });
});

it("clears and cancels the old conversation when switching workspaces", async () => {
  const other = "ws_" + "c".repeat(32);
  let activeSignal: AbortSignal | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, options?: RequestInit) => {
      if (input === "/api/workspaces")
        return Response.json({
          user_id: user,
          workspaces: [
            { id, name: "Engineering", role: "member" },
            { id: other, name: "Support", role: "member" },
          ],
        });
      if (input.endsWith("/documents")) return Response.json([]);
      if (input === "/api/session")
        return Response.json({ session_id: "old-session" });
      activeSignal = options?.signal || undefined;
      return new Promise<Response>((_, reject) => {
        activeSignal?.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        );
      });
    }),
  );
  render(<WorkspaceApp />);
  await screen.findByRole("heading", { name: "Engineering" });
  fireEvent.change(screen.getByLabelText("Ask your workspace"), {
    target: { value: "Engineering-only question" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send question" }));
  await screen.findByText("Looking for supporting context…");
  // Wait for the streaming request to start after session creation.
  const { waitFor } = await import("@testing-library/react");
  await waitFor(() => expect(activeSignal).toBeDefined());
  fireEvent.change(screen.getByLabelText("Current workspace"), {
    target: { value: other },
  });
  expect(
    await screen.findByRole("heading", { name: "Support" }),
  ).toBeInTheDocument();
  expect(activeSignal?.aborted).toBe(true);
  expect(
    screen.queryByText("Engineering-only question"),
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText("Ask your workspace")).toHaveValue("");
});
