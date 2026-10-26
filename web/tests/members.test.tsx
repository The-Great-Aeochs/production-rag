import { it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MembersPanel } from "@/components/workspace/members";
it("requires a separate confirmation before removing a member", async () => {
  const change = vi.fn().mockResolvedValue(true);
  render(
    <MembersPanel
      members={[{ user_id: "usr_" + "a".repeat(64), role: "member" }]}
      userId="another"
      busy={false}
      onChange={change}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  expect(change).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(
    screen.queryByText("Remove this member’s workspace access?"),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove member" }));
  expect(change).toHaveBeenCalledWith("usr_" + "a".repeat(64), null);
});

it("does not change access until the edited role is explicitly saved", () => {
  const change = vi.fn().mockResolvedValue(true);
  const memberId = "usr_" + "b".repeat(64);
  render(
    <MembersPanel
      members={[{ user_id: memberId, role: "member" }]}
      userId="another"
      busy={false}
      onChange={change}
    />,
  );
  const save = screen.getByRole("button", { name: "Save role" });
  expect(save).toBeDisabled();
  fireEvent.change(screen.getByLabelText(`Role for ${memberId}`), {
    target: { value: "admin" },
  });
  expect(change).not.toHaveBeenCalled();
  expect(save).toBeEnabled();
  fireEvent.click(save);
  expect(change).toHaveBeenCalledWith(memberId, "admin");
});
