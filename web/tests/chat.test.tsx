import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WorkspaceChat } from "@/components/workspace/chat";
import { WorkspaceApp } from "@/components/workspace";
const workspace = "ws_" + "a".repeat(32);
afterEach(() => vi.unstubAllGlobals());
it("stops an active answer and creates a fresh session for the next question", async () => {
  const signals: AbortSignal[] = [];
  let sessions = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, options: RequestInit) => {
      const headers = new Headers(options.headers);
      expect(headers.get("X-Workspace-ID")).toBe(workspace);
      if (path === "/api/session")
        return Response.json({ session_id: `session-${++sessions}` });
      const signal = options.signal as AbortSignal;
      signals.push(signal);
      return new Promise<Response>((_, reject) =>
        signal.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        ),
      );
    }),
  );
  render(<WorkspaceChat workspaceId={workspace} hasDocuments />);
  fireEvent.change(screen.getByLabelText("Ask your workspace"), {
    target: { value: "First question" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send question" }));
  await waitFor(() => expect(signals).toHaveLength(1));
  fireEvent.click(screen.getByRole("button", { name: "Stop response" }));
  expect(signals[0].aborted).toBe(true);
  expect(screen.getByText("Incomplete")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Ask your workspace"), {
    target: { value: "Second question" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send question" }));
  await waitFor(() => expect(signals).toHaveLength(2));
  expect(sessions).toBe(2);
});
it("keeps the conversation when opening another section of the same workspace", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      if (path === "/api/workspaces")
        return Response.json({
          user_id: "usr_test",
          workspaces: [{ id: workspace, name: "Engineering", role: "member" }],
        });
      if (path.endsWith("/documents")) return Response.json([]);
      if (path === "/api/session")
        return Response.json({ session_id: "session-1" });
      return new Response(
        'data: {"token":"A cited answer."}\n\ndata: {"done":true}\n\n',
        { headers: { "Content-Type": "text/event-stream" } },
      );
    }),
  );
  render(<WorkspaceApp />);
  await screen.findByRole("heading", { name: "Engineering" });
  fireEvent.change(screen.getByLabelText("Ask your workspace"), {
    target: { value: "Question" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send question" }));
  expect(await screen.findByText("A cited answer.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Documents" }));
  expect(
    await screen.findByRole("heading", { name: "Documents" }),
  ).toBeVisible();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Chat" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Chat" }));
  expect(screen.getByText("A cited answer.")).toBeVisible();
});
