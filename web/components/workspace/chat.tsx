"use client";
import { useWorkspaceChat } from "./use-workspace-chat";
import { AnswerMarkdown, Sources } from "@/components/answer";
export function WorkspaceChat({
  workspaceId,
  hasDocuments,
}: {
  workspaceId: string;
  hasDocuments: boolean;
}) {
  const chat = useWorkspaceChat(workspaceId);
  return (
    <>
      <div
        className="workspace-messages"
        role="log"
        aria-label="Conversation"
        aria-live="polite"
        aria-busy={chat.sending}
      >
        {!chat.messages.length && (
          <div className="chat-intro">
            <h2>Ask about your documents</h2>
            <p>
              {hasDocuments
                ? "Answers include excerpts from this workspace’s documents."
                : "No documents are connected yet. Ask a workspace administrator to connect a source."}
            </p>
          </div>
        )}
        {chat.messages.map((message) => (
          <article key={message.id} className={`chat-message ${message.role}`}>
            <p className="chat-message-role">
              {message.role === "user" ? "You" : "Answer"}
              {message.failed && <span>Incomplete</span>}
            </p>
            <AnswerMarkdown>
              {message.content ||
                (message.failed
                  ? "No complete answer received."
                  : "Searching documents…")}
            </AnswerMarkdown>
            {message.sources && <Sources sources={message.sources} />}
          </article>
        ))}
      </div>
      {chat.error && (
        <p className="inline-error" role="alert">
          {chat.error}
        </p>
      )}
      <form className="workspace-composer" onSubmit={chat.ask}>
        <label htmlFor="workspace-question">Ask your workspace</label>
        <textarea
          id="workspace-question"
          value={chat.question}
          onChange={(e) => chat.setQuestion(e.target.value)}
          maxLength={4000}
          disabled={chat.sending}
          rows={2}
          aria-describedby="workspace-help"
        />
        <div>
          <span id="workspace-help">Uses documents in this workspace.</span>
          {chat.sending ? (
            <button
              type="button"
              className="button secondary"
              onClick={chat.stop}
            >
              Stop response
            </button>
          ) : (
            <button
              type="submit"
              className="button primary"
              disabled={!chat.question.trim()}
            >
              Send question
            </button>
          )}
        </div>
      </form>
    </>
  );
}
