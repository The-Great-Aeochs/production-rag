"use client";
import { useState } from "react";
import { Plus } from "lucide-react";
import type { Workspace, WorkspaceView } from "@/lib/workspace";
const views: { id: WorkspaceView; label: string; admin?: boolean }[] = [
  { id: "chat", label: "Chat" },
  { id: "documents", label: "Documents" },
  { id: "members", label: "Members", admin: true },
  { id: "activity", label: "Access activity", admin: true },
];
export function WorkspaceSidebar({
  workspaces,
  selected,
  userId,
  view,
  busy,
  onSelect,
  onView,
  onCreate,
}: {
  workspaces: Workspace[];
  selected: string;
  userId: string;
  view: WorkspaceView;
  busy: boolean;
  onSelect: (id: string) => void;
  onView: (view: WorkspaceView) => void;
  onCreate: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const admin = workspaces.find((w) => w.id === selected)?.role === "admin";
  return (
    <aside className="workspace-sidebar">
      <label htmlFor="workspace-select">Current workspace</label>
      <select
        id="workspace-select"
        value={selected}
        onChange={(e) => onSelect(e.target.value)}
        disabled={!workspaces.length || busy}
      >
        {!workspaces.length && <option value="">No workspaces yet</option>}
        {workspaces.map((w) => (
          <option key={w.id} value={w.id}>
            {w.name}
          </option>
        ))}
      </select>
      <button className="sidebar-new" onClick={onCreate} disabled={busy}>
        <Plus size={15} aria-hidden="true" /> New workspace
      </button>
      <nav className="workspace-tabs" aria-label="Workspace sections">
        {views
          .filter((item) => !item.admin || admin)
          .map((item) => (
            <button
              key={item.id}
              aria-current={view === item.id ? "page" : undefined}
              onClick={() => onView(item.id)}
              disabled={!selected || busy}
            >
              {item.label}
            </button>
          ))}
      </nav>
      <details className="workspace-profile">
        <summary>Your user ID</summary>
        <p>Share this ID with a workspace admin to join their workspace.</p>
        <code>{userId || "Unavailable"}</code>
        <button
          className="button secondary"
          disabled={!userId}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(userId);
              setCopied(true);
              setCopyFailed(false);
            } catch {
              setCopyFailed(true);
            }
          }}
        >
          {copied ? "Copied" : "Copy user ID"}
        </button>
        {copyFailed && <p role="status">Select and copy the ID above.</p>}
      </details>
    </aside>
  );
}
