"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { LoaderCircle } from "lucide-react";
import { api } from "@/lib/api-client";
import {
  errorMessage,
  roleLabels,
  type AuditEvent,
  type Member,
  type Role,
  type Workspace,
  type WorkspaceDocument,
  type WorkspaceList,
  type WorkspaceView,
} from "@/lib/workspace";
import { WorkspaceChat } from "./workspace/chat";
import { WorkspaceSidebar } from "./workspace/sidebar";
import { DocumentsPanel } from "./workspace/documents";
import { MembersPanel } from "./workspace/members";
import { ActivityPanel } from "./workspace/activity";

export function WorkspaceApp() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selected, setSelected] = useState("");
  const [userId, setUserId] = useState("");
  const [initializing, setInitializing] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState<WorkspaceView>("chat");
  const [documents, setDocuments] = useState<WorkspaceDocument[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [activity, setActivity] = useState<AuditEvent[]>([]);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const active = workspaces.find((workspace) => workspace.id === selected);
  const viewRequest = useRef<AbortController | null>(null);
  const isAdmin = active?.role === "admin";

  useEffect(() => {
    const controller = new AbortController();
    api<WorkspaceList>("workspaces", { signal: controller.signal })
      .then((data) => {
        if (controller.signal.aborted) return;
        setWorkspaces(data.workspaces);
        setUserId(data.user_id);
        setSelected(data.workspaces[0]?.id || "");
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setError(errorMessage(error, "Could not load workspaces."));
      })
      .finally(() => {
        if (!controller.signal.aborted) setInitializing(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    viewRequest.current?.abort();
    setBusy(false);
    setView("chat");
    setDocuments([]);
    setMembers([]);
    setActivity([]);
    setError("");
    setNotice("");
    if (!selected) return;
    const controller = new AbortController();
    api<WorkspaceDocument[]>(`workspaces/${selected}/documents`, {
      signal: controller.signal,
    })
      .then((data) => {
        if (!controller.signal.aborted) setDocuments(data);
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setError(errorMessage(error, "Could not load documents."));
      });
    return () => {
      controller.abort();
      viewRequest.current?.abort();
    };
  }, [selected]);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (busy || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const workspace = await api<Workspace>("workspaces", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      setWorkspaces((old) => [...old, workspace]);
      setSelected(workspace.id);
      setCreating(false);
      setName("");
    } catch (error) {
      setError(errorMessage(error, "Could not create workspace."));
    } finally {
      setBusy(false);
    }
  }

  async function selectView(next: WorkspaceView) {
    if (busy) return;
    viewRequest.current?.abort();
    setView(next);
    setError("");
    setNotice("");
    if (next === "chat") return;
    const controller = new AbortController();
    viewRequest.current = controller;
    setBusy(true);
    try {
      if (next === "documents") {
        const data = await api<WorkspaceDocument[]>(
          `workspaces/${selected}/documents`,
          { signal: controller.signal },
        );
        if (!controller.signal.aborted) setDocuments(data);
      } else if (next === "members") {
        const data = await api<Member[]>(`workspaces/${selected}/members`, {
          signal: controller.signal,
        });
        if (!controller.signal.aborted) setMembers(data);
      } else {
        const data = await api<AuditEvent[]>(`workspaces/${selected}/audit`, {
          signal: controller.signal,
        });
        if (!controller.signal.aborted) setActivity(data);
      }
    } catch (error) {
      if (!controller.signal.aborted)
        setError(errorMessage(error, "Could not load workspace data."));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  async function changeMember(id: string, role: Role | null): Promise<boolean> {
    if (busy) return false;
    setBusy(true);
    setError("");
    try {
      await api<void>(`workspaces/${selected}/members/${id}`, {
        method: role ? "PUT" : "DELETE",
        ...(role ? { body: JSON.stringify({ role }) } : {}),
      });
      const data = await api<WorkspaceList>("workspaces");
      setWorkspaces(data.workspaces);
      const updated = data.workspaces.find(
        (workspace) => workspace.id === selected,
      );
      if (!updated) setSelected(data.workspaces[0]?.id || "");
      else if (updated.role !== "admin") {
        setView("chat");
        setMembers([]);
        setActivity([]);
      } else setMembers(await api<Member[]>(`workspaces/${selected}/members`));
      setNotice(role ? "Member role saved." : "Member access removed.");
      return true;
    } catch (error) {
      setError(errorMessage(error, "Could not change membership."));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function sync() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api<{ job_id: string }>(`workspaces/${selected}/ingest`, {
        method: "POST",
      });
      setNotice(
        "Source refresh queued. Open Documents again after processing to see updates.",
      );
    } catch (error) {
      setError(errorMessage(error, "Could not refresh source."));
    } finally {
      setBusy(false);
    }
  }

  if (initializing)
    return (
      <div className="workspace-loading" role="status">
        <LoaderCircle className="spin" size={20} aria-hidden="true" /> Loading
        workspaces…
      </div>
    );
  return (
    <div className="workspace-shell">
      <WorkspaceSidebar
        workspaces={workspaces}
        selected={selected}
        userId={userId}
        view={view}
        busy={busy}
        onSelect={setSelected}
        onView={selectView}
        onCreate={() => setCreating(true)}
      />
      <section className="workspace-content">
        <div className="workspace-top">
          <h1>{active?.name || "Workspaces"}</h1>
          {active && (
            <span className="workspace-role">{roleLabels[active.role]}</span>
          )}
        </div>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="inline-notice" role="status">
            {notice}
          </p>
        )}
        {creating && (
          <form className="workspace-create" onSubmit={create}>
            <label htmlFor="workspace-name">Workspace name</label>
            <div>
              <input
                id="workspace-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={80}
                required
                autoFocus
              />
              <button
                className="button primary"
                disabled={busy || !name.trim()}
                type="submit"
              >
                Create workspace
              </button>
              <button
                className="button secondary"
                type="button"
                disabled={busy}
                onClick={() => setCreating(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
        {!active && !creating && (
          <div className="workspace-empty">
            <h2>No workspaces yet</h2>
            <p>
              Create a workspace for your documents, or share your user ID with
              an admin to join an existing one.
            </p>
            <button
              className="button primary"
              onClick={() => setCreating(true)}
            >
              Create workspace
            </button>
          </div>
        )}
        {active && (
          <>
            <div hidden={view !== "chat"}>
              <WorkspaceChat
                key={selected}
                workspaceId={selected}
                hasDocuments={documents.length > 0}
              />
            </div>
            {busy && (view === "members" || view === "activity") && (
              <p role="status">Loading workspace data…</p>
            )}
            {view === "documents" && (
              <DocumentsPanel
                documents={documents}
                canEdit={active.role !== "member"}
                busy={busy}
                onSync={sync}
              />
            )}
            {view === "members" && isAdmin && (
              <MembersPanel
                key={selected}
                members={members}
                userId={userId}
                busy={busy}
                onChange={changeMember}
              />
            )}
            {view === "activity" && isAdmin && (
              <ActivityPanel events={activity} loading={busy} />
            )}
          </>
        )}
      </section>
    </div>
  );
}
