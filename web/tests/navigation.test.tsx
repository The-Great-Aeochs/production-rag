import { expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Nav } from "@/components/nav";
it("closes navigation on Escape and returns focus to its toggle", () => {
  render(<Nav />);
  const toggle = screen.getByRole("button", { name: "Toggle navigation" });
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  const docs = screen.getByRole("link", { name: "Docs" });
  docs.focus();
  fireEvent.keyDown(docs, { key: "Escape" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(toggle).toHaveFocus();
});
