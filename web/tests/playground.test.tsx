import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Playground } from "@/components/playground";
afterEach(() => vi.unstubAllGlobals());
function submitQuestion(question = "How are documents scoped?") {
  fireEvent.change(screen.getByLabelText("Ask a question about the project"), {
    target: { value: question },
  });
  fireEvent.click(screen.getByRole("button", { name: "Ask question" }));
}
describe("public demo", () => {
  it("labels prewritten answers and exposes the source through an accessible disclosure", () => {
    render(<Playground />);
    expect(screen.getByText("Sample answer")).toBeInTheDocument();
    const source = screen.getByRole("button", {
      name: /View source: retrieval.md/,
    });
    expect(source).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(source);
    expect(source).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/Both backends enforce/)).toBeVisible();
    fireEvent.click(source);
    expect(screen.getByText(/Both backends enforce/)).not.toBeVisible();
  });
  it("updates the answer and selected question together", () => {
    render(<Playground />);
    const question = screen.getByRole("button", {
      name: /What happens if an ingestion/,
    });
    fireEvent.click(question);
    expect(question).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Jobs remain in Postgres/)).toBeVisible();
    expect(
      screen.getByRole("heading", {
        name: "What happens if an ingestion worker crashes?",
      }),
    ).toBeInTheDocument();
  });
  it("does not offer a failing form when live questions are not configured", () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    render(<Playground />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Live questions are unavailable",
    );
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Can cached answers/ }));
    expect(
      screen.getByText(/Conversation answers are not stored/),
    ).toBeVisible();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("keeps the sample available after an unavailable live request", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json(
            { detail: "Live demo is not connected" },
            { status: 503 },
          ),
        ),
    );
    render(<Playground liveAvailable />);
    submitQuestion();
    expect(await screen.findByRole("alert")).toHaveTextContent("not connected");
    expect(screen.getByText("Sample answer")).toBeInTheDocument();
  });
  it("labels a live answer and blocks model HTML and remote images", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({
          answer:
            'A live answer <img src=x onerror="alert(1)" /> ![tracker](https://tracker.example/leak)',
          sources: [],
        }),
      ),
    );
    const { container } = render(<Playground liveAvailable />);
    submitQuestion("What is a workspace?");
    expect(await screen.findByText("Live response")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    fireEvent.change(
      screen.getByLabelText("Ask a question about the project"),
      { target: { value: "An unsubmitted question" } },
    );
    expect(
      screen.getByRole("heading", { name: "What is a workspace?" }),
    ).toBeInTheDocument();
  });
});
