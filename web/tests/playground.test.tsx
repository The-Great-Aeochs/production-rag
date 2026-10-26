import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Playground } from "@/components/playground";
afterEach(() => vi.unstubAllGlobals());
describe("public playground", () => {
  it("labels guided answers and exposes their source excerpt", () => {
    render(<Playground />);
    expect(screen.getByText("Guided example")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retrieval.md/ }));
    expect(screen.getByText(/Both backends enforce/)).toBeInTheDocument();
  });
  it("switches the guided context when another question is selected", () => {
    render(<Playground />);
    fireEvent.click(
      screen.getByRole("button", { name: /What happens if an ingestion/ }),
    );
    expect(screen.getByText(/Jobs remain in Postgres/)).toBeInTheDocument();
    expect(
      screen.getByLabelText("Ask a question about the project"),
    ).toHaveValue("What happens if an ingestion worker crashes?");
  });
  it("keeps examples available when live inference is disconnected", async () => {
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
    render(<Playground />);
    fireEvent.click(screen.getByRole("button", { name: "Ask live question" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not connected");
    expect(screen.getByText("Guided example")).toBeInTheDocument();
  });
  it("labels real responses separately and never renders raw model HTML", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Ask live question" }));
    expect(await screen.findByText("Live response")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
