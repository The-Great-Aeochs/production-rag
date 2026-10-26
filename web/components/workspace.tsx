"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowUp,
  BookOpen,
  Check,
  ChevronDown,
  Copy,
  FileText,
  FolderOpen,
  LoaderCircle,
  MessageSquare,
  Plus,
  RefreshCw,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { readEvents, type Source } from "@/lib/sse";

type Workspace = {
  id: string;
  name: string;
  role: "member" | "editor" | "admin";
};
type Document = { source_path: string; type: string; status: string };
type Member = { user_id: string; role: string };
type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  failed?: boolean;
};
type Audit = {
  actor_id: string;
  target_id: string | null;
  action: string;
  role: string | null;
  created_at: string;
};
async function api(path: string, options: RequestInit = {}) {
  const response = await fetch(`/api/${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = "Request failed. Please try again.";
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}
export function WorkspaceApp() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]),
    [selected, setSelected] = useState("");
  const [userId, setUserId] = useState("");
  const [initializing, setInitializing] = useState(true),
    [error, setError] = useState("");
  const [tab, setTab] = useState<"chat" | "documents" | "members" | "activity">(
    "chat",
  );
  const [documents, setDocuments] = useState<Document[]>([]),
    [members, setMembers] = useState<Member[]>([]),
    [activity, setActivity] = useState<Audit[]>([]);
  const [messages, setMessages] = useState<Message[]>([]),
    [question, setQuestion] = useState(""),
    [session, setSession] = useState<string>(),
    [sending, setSending] = useState(false);
  const [creating, setCreating] = useState(false),
    [name, setName] = useState("");
  const [newMember, setNewMember] = useState(""),
    [memberRole, setMemberRole] = useState("member");
  const [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(""),
    [source, setSource] = useState<Source>();
  const active = workspaces.find((w) => w.id === selected);
  const stream = useRef<AbortController | null>(null);
  const tabRequest = useRef<AbortController | null>(null);
  const canEdit = active?.role === "editor" || active?.role === "admin";
  const isAdmin = active?.role === "admin";
  async function reload(signal?: AbortSignal) {
    const data = await api("workspaces", { signal });
    setWorkspaces(data.workspaces);
    setUserId(data.user_id);
    setSelected((previous) =>
      data.workspaces.some((w: Workspace) => w.id === previous)
        ? previous
        : data.workspaces[0]?.id || "",
    );
  }
  useEffect(() => {
    const controller = new AbortController();
    reload(controller.signal)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setInitializing(false);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    stream.current?.abort();
    tabRequest.current?.abort();
    setBusy(false);
    setSending(false);
    setMessages([]);
    setQuestion("");
    setSession(undefined);
    setSource(undefined);
    setTab("chat");
    setDocuments([]);
    setMembers([]);
    setActivity([]);
    setError("");
    setNotice("");
    if (!selected) return;
    const controller = new AbortController();
    api(`workspaces/${selected}/documents`, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setDocuments(data);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [selected]);
  useEffect(
    () => () => {
      stream.current?.abort();
      tabRequest.current?.abort();
    },
    [],
  );
  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const workspace = await api("workspaces", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      setWorkspaces((old) => [...old, workspace]);
      setSelected(workspace.id);
      setCreating(false);
      setName("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create workspace");
    } finally {
      setBusy(false);
    }
  }
  async function selectTab(next: typeof tab) {
    if (busy) return;
    tabRequest.current?.abort();
    setBusy(false);
    setTab(next);
    setError("");
    setNotice("");
    if (next === "members" || next === "activity") {
      const controller = new AbortController();
      tabRequest.current = controller;
      setBusy(true);
      try {
        const data = await api(
          `workspaces/${selected}/${next === "members" ? "members" : "audit"}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        if (next === "members") setMembers(data);
        else setActivity(data);
      } catch (e) {
        if (controller.signal.aborted) return;
        setError(
          e instanceof Error ? e.message : "Could not load workspace data",
        );
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }
  }
  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || sending || !selected) return;
    setError("");
    const text = question;
    setQuestion("");
    setSending(true);
    const controller = new AbortController();
    stream.current = controller;
    const id = crypto.randomUUID();
    setMessages((old) => [
      ...old,
      { id: crypto.randomUUID(), role: "user", content: text },
      { id, role: "assistant", content: "" },
    ]);
    try {
      let sid = session;
      if (!sid) {
        const data = await api("session", {
          method: "POST",
          headers: { "X-Workspace-ID": selected },
          signal: controller.signal,
        });
        sid = data.session_id;
        if (controller.signal.aborted) return;
        setSession(sid);
      }
      const response = await fetch("/api/query/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Workspace-ID": selected,
        },
        body: JSON.stringify({ query: text, session_id: sid }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        let detail = "Could not start response";
        try {
          const data = await response.json();
          if (typeof data.detail === "string") detail = data.detail;
        } catch {}
        throw new Error(detail);
      }
      await readEvents(response.body, (event) =>
        setMessages((old) =>
          old.map((message) =>
            message.id === id
              ? {
                  ...message,
                  content: message.content + (event.token || ""),
                  sources: event.sources || message.sources,
                }
              : message,
          ),
        ),
      );
    } catch (e) {
      if (!controller.signal.aborted) {
        setMessages((old) =>
          old.map((message) =>
            message.id === id ? { ...message, failed: true } : message,
          ),
        );
        setError(
          e instanceof Error ? e.message : "The response was interrupted",
        );
        setSession(undefined);
      }
    } finally {
      if (stream.current === controller) {
        stream.current = null;
        setSending(false);
      }
    }
  }
  async function changeMember(id: string, role: string | null) {
    setBusy(true);
    setError("");
    try {
      await api(`workspaces/${selected}/members/${id}`, {
        method: role ? "PUT" : "DELETE",
        ...(role ? { body: JSON.stringify({ role }) } : {}),
      });
      const data = await api("workspaces");
      setWorkspaces(data.workspaces);
      const updated = data.workspaces.find((w: Workspace) => w.id === selected);
      if (!updated) {
        setSelected(data.workspaces[0]?.id || "");
        return;
      }
      if (updated.role !== "admin") {
        setTab("chat");
        setMembers([]);
        setActivity([]);
        return;
      }
      setMembers(await api(`workspaces/${selected}/members`));
      setNewMember("");
      setNotice(role ? "Workspace role updated." : "Workspace access revoked.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change membership");
    } finally {
      setBusy(false);
    }
  }
  async function sync() {
    setBusy(true);
    setError("");
    try {
      const job = await api(`workspaces/${selected}/ingest`, {
        method: "POST",
      });
      setNotice(`Refresh queued. Job ${job.job_id.slice(0, 8)}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not refresh source");
    } finally {
      setBusy(false);
    }
  }
  if (initializing)
    return (
      <div className="workspace-loading">
        <LoaderCircle className="spin" size={23} /> Opening your workspaces…
      </div>
    );
  return (
    <div className="workspace-shell">
      <aside className="workspace-sidebar">
        <div className="sidebar-label">YOUR WORKSPACES</div>
        <div className="workspace-picker">
          <label htmlFor="workspace-select" className="sr-only">
            Current workspace
          </label>
          <select
            id="workspace-select"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            disabled={!workspaces.length || busy}
          >
            {!workspaces.length && <option value="">No workspaces yet</option>}
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
          <ChevronDown size={14} />
        </div>
        <button
          className="sidebar-new"
          disabled={busy}
          onClick={() => setCreating(true)}
        >
          <Plus size={14} /> New workspace
        </button>
        <div className="workspace-tabs">
          <button
            className={tab === "chat" ? "active" : ""}
            onClick={() => selectTab("chat")}
            disabled={!selected}
          >
            <MessageSquare size={16} /> Chat
          </button>
          <button
            className={tab === "documents" ? "active" : ""}
            onClick={() => selectTab("documents")}
            disabled={!selected}
          >
            <FileText size={16} /> Documents <span>{documents.length}</span>
          </button>
          {isAdmin && (
            <>
              <button
                className={tab === "members" ? "active" : ""}
                onClick={() => selectTab("members")}
              >
                <Users size={16} /> Members
              </button>
              <button
                className={tab === "activity" ? "active" : ""}
                onClick={() => selectTab("activity")}
              >
                <ShieldCheck size={16} /> Access activity
              </button>
            </>
          )}
        </div>
        <div className="workspace-profile">
          <span className="sidebar-label">YOUR WORKSPACE USER ID</span>
          <code>{userId || "Unavailable"}</code>
          <button
            disabled={!userId}
            onClick={() =>
              navigator.clipboard
                .writeText(userId)
                .then(() => setNotice("User ID copied."))
                .catch(() => setError("Select and copy the user ID above."))
            }
          >
            <Copy size={12} /> Copy ID
          </button>
          <p>Share this ID with a workspace admin to be added.</p>
        </div>
      </aside>
      <section className="workspace-content">
        <div className="workspace-top">
          <div>
            <span className="eyebrow">WORKSPACE / {tab.toUpperCase()}</span>
            <h1>{active?.name || "Make room for your knowledge."}</h1>
          </div>
          {active && (
            <span className="workspace-role">
              <ShieldCheck size={13} />
              {active.role}
            </span>
          )}
        </div>
        {error && (
          <div className="inline-error" role="alert">
            {error}
          </div>
        )}
        {notice && (
          <div className="inline-notice" role="status">
            <Check size={14} />
            {notice}
          </div>
        )}
        {creating && (
          <form className="workspace-create" onSubmit={create}>
            <label htmlFor="workspace-name">Name your workspace</label>
            <div>
              <input
                id="workspace-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Engineering handbook"
                maxLength={80}
                required
              />
              <button
                className="button primary"
                disabled={busy || !name.trim()}
                type="submit"
              >
                Create
              </button>
              <button
                className="icon-button"
                type="button"
                onClick={() => setCreating(false)}
                aria-label="Cancel new workspace"
              >
                <X size={18} />
              </button>
            </div>
          </form>
        )}
        {!selected && !creating && (
          <div className="workspace-empty">
            <FolderOpen size={35} />
            <h2>A workspace is your own corner.</h2>
            <p>
              Create one to keep documents, conversations, and permissions
              together.
            </p>
            <button
              className="button primary"
              onClick={() => setCreating(true)}
            >
              Create a workspace <Plus size={15} />
            </button>
          </div>
        )}
        {selected && tab === "chat" && (
          <>
            <div className="workspace-messages" aria-live="polite">
              {messages.length === 0 && (
                <div className="chat-intro">
                  <div className="chat-intro-icon">
                    <MessageSquare size={25} />
                  </div>
                  <h2>Start with a question.</h2>
                  <p>
                    {documents.length
                      ? "Answers will use the documents in this workspace, with sources attached."
                      : "Your workspace is ready. Ask an administrator to connect a document source, then ask questions here."}
                  </p>
                </div>
              )}
              {messages.map((message) => (
                <article
                  key={message.id}
                  className={`chat-message ${message.role}`}
                >
                  <div className="chat-message-role">
                    {message.role === "user" ? "YOU" : "PRODUCTION RAG"}
                    {message.failed && <span>Interrupted</span>}
                  </div>
                  <div className="markdown">
                    <ReactMarkdown skipHtml components={{ img: () => null }}>
                      {message.content ||
                        (!message.failed
                          ? "Looking for supporting context…"
                          : "No complete answer received.")}
                    </ReactMarkdown>
                  </div>
                  {message.sources && (
                    <div className="source-list">
                      {message.sources.map((item, index) => (
                        <button
                          key={index}
                          className="source-chip"
                          onClick={() => setSource(item)}
                        >
                          <BookOpen size={12} />
                          {item.source_path}
                        </button>
                      ))}
                    </div>
                  )}
                </article>
              ))}
            </div>
            <form className="workspace-composer" onSubmit={ask}>
              <label className="sr-only" htmlFor="workspace-question">
                Ask your workspace
              </label>
              <textarea
                id="workspace-question"
                placeholder="Ask a question about your documents…"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={4000}
                disabled={sending}
                rows={2}
              />
              <div>
                <span>Answers stay inside this workspace.</span>
                <button
                  className="ask-submit"
                  type="submit"
                  aria-label="Send question"
                  disabled={sending || !question.trim()}
                >
                  {sending ? (
                    <LoaderCircle className="spin" size={18} />
                  ) : (
                    <ArrowUp size={18} />
                  )}
                </button>
              </div>
            </form>
          </>
        )}
        {selected && tab === "documents" && (
          <div className="workspace-panel">
            <div className="panel-heading">
              <div>
                <h2>Connected documents</h2>
                <p>The sources available to this workspace.</p>
              </div>
              {canEdit && (
                <button
                  className="button secondary"
                  onClick={sync}
                  disabled={busy}
                >
                  <RefreshCw size={14} /> Refresh source
                </button>
              )}
            </div>
            {documents.length ? (
              <div className="document-table">
                {documents.map((doc) => (
                  <div key={doc.source_path}>
                    <FileText size={17} />
                    <span>
                      {doc.source_path}
                      <small>{doc.type}</small>
                    </span>
                    <span className="document-status">{doc.status}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-small">
                <FolderOpen size={28} />
                <h3>No source connected yet</h3>
                <p>
                  Ask an administrator to connect a document source. Public file
                  uploads are not enabled in this release.
                </p>
              </div>
            )}
          </div>
        )}
        {selected && tab === "members" && isAdmin && (
          <div className="workspace-panel">
            <div className="panel-heading">
              <div>
                <h2>People & permissions</h2>
                <p>Roles apply only to this workspace.</p>
              </div>
            </div>
            <form
              className="member-form"
              onSubmit={(event) => {
                event.preventDefault();
                changeMember(newMember, memberRole);
              }}
            >
              <label htmlFor="member-id">
                Add a teammate by workspace user ID
              </label>
              <p>
                They can copy it after signing in and opening their workspace
                page.
              </p>
              <div>
                <input
                  id="member-id"
                  placeholder="usr_…"
                  value={newMember}
                  onChange={(e) => setNewMember(e.target.value)}
                  pattern="usr_[a-f0-9]{64}"
                  required
                />
                <select
                  aria-label="New member role"
                  value={memberRole}
                  onChange={(e) => setMemberRole(e.target.value)}
                >
                  <option value="member">Member</option>
                  <option value="editor">Editor</option>
                  <option value="admin">Admin</option>
                </select>
                <button
                  className="button primary"
                  disabled={busy}
                  type="submit"
                >
                  Add
                </button>
              </div>
            </form>
            <div className="member-list">
              {members.map((member) => (
                <div key={member.user_id}>
                  <code title={member.user_id}>
                    {member.user_id}
                    {member.user_id === userId ? " (you)" : ""}
                  </code>
                  <select
                    aria-label={`Role for ${member.user_id}`}
                    value={member.role}
                    disabled={busy}
                    onChange={(e) =>
                      changeMember(member.user_id, e.target.value)
                    }
                  >
                    <option value="member">Member</option>
                    <option value="editor">Editor</option>
                    <option value="admin">Admin</option>
                  </select>
                  <button
                    type="button"
                    className="revoke-button"
                    onClick={() => changeMember(member.user_id, null)}
                    disabled={busy}
                  >
                    Revoke
                  </button>
                </div>
              ))}
            </div>
            <p className="panel-footnote">
              Every role change is recorded. A workspace must retain at least
              one admin.
            </p>
          </div>
        )}
        {selected && tab === "activity" && isAdmin && (
          <div className="workspace-panel">
            <div className="panel-heading">
              <div>
                <h2>Access activity</h2>
                <p>Recent membership and source refresh events.</p>
              </div>
            </div>
            <div className="audit-list">
              {activity.map((event, index) => (
                <div key={index}>
                  <ShieldCheck size={16} />
                  <span>
                    <strong>{event.action}</strong>
                    <small>
                      {event.target_id || event.actor_id}
                      {event.role ? ` · ${event.role}` : ""}
                    </small>
                  </span>
                  <time dateTime={event.created_at}>
                    {new Date(event.created_at).toLocaleDateString()}
                  </time>
                </div>
              ))}
            </div>
          </div>
        )}
        {source && (
          <div className="source-drawer">
            <div>
              <h3>{source.source_path}</h3>
              <button
                className="icon-button"
                onClick={() => setSource(undefined)}
                aria-label="Close source"
              >
                <X size={17} />
              </button>
            </div>
            <p>{source.section_path?.join(" / ")}</p>
            <pre>{source.content || "No excerpt available."}</pre>
          </div>
        )}
      </section>
    </div>
  );
}
