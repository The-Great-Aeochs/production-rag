"use client";
import { useState, type FormEvent } from "react";
import {
  ArrowUp,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronRight,
  LoaderCircle,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { examples } from "@/lib/samples";
import type { Source } from "@/lib/sse";

export function Playground({
  liveAvailable = false,
}: {
  liveAvailable?: boolean;
}) {
  const [selected, setSelected] = useState(0);
  const [question, setQuestion] = useState(examples[0].question);
  const [answeredQuestion, setAnsweredQuestion] = useState(
    examples[0].question,
  );
  const [answer, setAnswer] = useState(examples[0].answer);
  const [sources, setSources] = useState<Source[]>([
    {
      source_path: examples[0].source,
      section_path: [examples[0].section],
      content: examples[0].excerpt,
    },
  ]);
  const [mode, setMode] = useState<"guided" | "live">("guided");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  function choose(index: number) {
    setSelected(index);
    setQuestion(examples[index].question);
    setAnswer(examples[index].answer);
    setAnsweredQuestion(examples[index].question);
    setSources([
      {
        source_path: examples[index].source,
        section_path: [examples[index].section],
        content: examples[index].excerpt,
      },
    ]);
    setMode("guided");
    setError("");
    setExpanded(false);
  }
  async function ask(event: FormEvent) {
    event.preventDefault();
    if (loading || !question.trim()) return;
    setError("");
    setLoading(true);
    const submittedQuestion = question;
    try {
      const response = await fetch("/api/demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: question }),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : "Live answers are temporarily unavailable",
        );
      setAnswer(data.answer);
      setAnsweredQuestion(submittedQuestion);
      setSources(data.sources || []);
      setMode("live");
      setExpanded(false);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Please try again");
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="playground" aria-busy={loading}>
      <div className="playground-top">
        <span>
          <span className="small-grid" /> THE PLAYGROUND
        </span>
        <span className="mode-badge">
          <span
            className={mode === "live" ? "status-dot live" : "status-dot"}
          />
          {mode === "live" ? "Live response" : "Guided example"}
        </span>
      </div>
      <div className="playground-grid">
        <aside className="example-rail">
          <div className="rail-label">A FEW GOOD QUESTIONS</div>
          {examples.map((example, index) => (
            <button
              key={example.source}
              type="button"
              onClick={() => choose(index)}
              className={selected === index ? "example active" : "example"}
              disabled={loading}
            >
              <span className="example-number">0{index + 1}</span>
              {example.question}
              <ChevronRight size={15} />
            </button>
          ))}
          <div className="rail-note">
            <BookOpen size={17} />
            <p>
              A curated corpus about this project. No private workspace data.
            </p>
          </div>
        </aside>
        <div className="answer-pane">
          <div className="answer-question">
            <span className="avatar user-avatar">Q</span>
            <h3>{answeredQuestion}</h3>
          </div>
          <div className="answer-body">
            <div className="answer-label">
              <span className="avatar ai-avatar">
                <Sparkles size={15} />
              </span>
              <span>PRODUCTION RAG</span>
              <span className="answer-complete">
                <Check size={13} />{" "}
                {mode === "guided" ? "Illustrative" : "Complete"}
              </span>
            </div>
            <div className="markdown">
              <ReactMarkdown skipHtml components={{ img: () => null }}>
                {answer}
              </ReactMarkdown>
            </div>
            {sources.length > 0 && (
              <div className="source-list">
                {sources.map((source, index) => (
                  <button
                    type="button"
                    className="source-chip"
                    onClick={() => setExpanded(!expanded)}
                    aria-expanded={expanded}
                    key={source.source_path + index}
                  >
                    <span>{index + 1}</span>
                    <BookOpen size={13} />
                    {source.source_path}
                    <ArrowUpRight size={12} />
                  </button>
                ))}
              </div>
            )}
            {expanded && (
              <div className="source-preview">
                {sources.map((source, index) => (
                  <div key={index}>
                    <strong>{source.source_path}</strong>
                    <p>{source.content || "Source excerpt is unavailable."}</p>
                  </div>
                ))}
              </div>
            )}
            <p className="answer-footnote">
              {mode === "guided"
                ? "This is a prewritten walkthrough, not a live model response."
                : "Generated from the public corpus. Check the cited sources."}
            </p>
          </div>
          <form className="ask-form" onSubmit={ask}>
            <label htmlFor="demo-question" className="sr-only">
              Ask a question about the project
            </label>
            <textarea
              id="demo-question"
              rows={2}
              maxLength={1000}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask a question about the project…"
              disabled={loading}
            />
            <div className="ask-form-bottom">
              <span>
                {liveAvailable
                  ? "Public demo · shared daily quota"
                  : "Explore examples, or check live availability"}
              </span>
              <button
                type="submit"
                className="ask-submit"
                aria-label="Ask live question"
                disabled={loading || !question.trim()}
              >
                {loading ? (
                  <LoaderCircle size={18} className="spin" />
                ) : (
                  <ArrowUp size={19} />
                )}
              </button>
            </div>
          </form>
          {error && (
            <div className="inline-error" role="alert">
              {error}
            </div>
          )}
          <button
            className="reset-example"
            onClick={() => choose(selected)}
            type="button"
            disabled={loading}
          >
            <RotateCcw size={12} /> Reset example
          </button>
        </div>
      </div>
    </div>
  );
}
