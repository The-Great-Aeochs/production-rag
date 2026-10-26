"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, responseError } from "@/lib/api-client";
import { readEvents, type Source } from "@/lib/sse";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  failed?: boolean;
};
export function useWorkspaceChat(workspaceId: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [session, setSession] = useState<string>();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const stream = useRef<AbortController | null>(null);
  useEffect(() => () => stream.current?.abort(), []);
  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || sending || !workspaceId) return;
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
        const data = await api<{ session_id: string }>("session", {
          method: "POST",
          headers: { "X-Workspace-ID": workspaceId },
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
          "X-Workspace-ID": workspaceId,
        },
        body: JSON.stringify({ query: text, session_id: sid }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        throw await responseError(response, "Could not start response");
      }
      await readEvents(
        response.body,
        (event) =>
          !controller.signal.aborted &&
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
      controller.abort();
      if (stream.current === controller) {
        stream.current = null;
        setSending(false);
      }
    }
  }
  function stop() {
    stream.current?.abort();
    setMessages((old) =>
      old.map((message, index) =>
        index === old.length - 1 ? { ...message, failed: true } : message,
      ),
    );
    setSending(false);
    setSession(undefined);
  }
  return { messages, question, setQuestion, sending, error, ask, stop };
}
