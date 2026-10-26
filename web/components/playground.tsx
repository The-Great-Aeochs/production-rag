"use client";
import { useState, type FormEvent } from "react";
import { LoaderCircle } from "lucide-react";
import { examples } from "@/lib/samples";
import type { Source } from "@/lib/sse";
import { AnswerMarkdown, Sources } from "@/components/answer";
import { responseError } from "@/lib/api-client";

type Answer = {
  question: string;
  answer: string;
  sources: Source[];
  live: boolean;
};
function sampleAnswer(index: number): Answer {
  const sample = examples[index];
  return {
    question: sample.question,
    answer: sample.answer,
    sources: [
      {
        source_path: sample.source,
        section_path: [sample.section],
        content: sample.excerpt,
      },
    ],
    live: false,
  };
}
export function Playground({
  liveAvailable = false,
}: {
  liveAvailable?: boolean;
}) {
  const [selected, setSelected] = useState(0);
  const [result, setResult] = useState(() => sampleAnswer(0));
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  function choose(index: number) {
    setSelected(index);
    setResult(sampleAnswer(index));
    setError("");
  }
  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!liveAvailable || loading || !question.trim()) return;
    const submittedQuestion = question.trim();
    setError("");
    setLoading(true);
    try {
      const response = await fetch("/api/demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: submittedQuestion }),
      });
      if (!response.ok)
        throw await responseError(
          response,
          "Could not get an answer. Try again.",
        );
      const data = await response.json();
      setResult({
        question: submittedQuestion,
        answer: data.answer,
        sources: data.sources || [],
        live: true,
      });
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Could not get an answer. Try again.",
      );
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="playground">
      <aside className="example-rail" aria-label="Sample questions">
        <h3>Sample questions</h3>
        {examples.map((example, index) => (
          <button
            key={example.source}
            type="button"
            className="example"
            aria-pressed={!result.live && selected === index}
            onClick={() => choose(index)}
            disabled={loading}
          >
            {example.question}
          </button>
        ))}
        <p>
          These sample answers are prewritten. Open a source to check the
          supporting text.
        </p>
      </aside>
      <div className="answer-pane">
        <div className="answer-result" aria-busy={loading}>
          <p className="answer-kind">
            {result.live ? "Live response" : "Sample answer"}
          </p>
          <h3>{result.question}</h3>
          <AnswerMarkdown>{result.answer}</AnswerMarkdown>
          <Sources
            key={`${result.question}-${result.live}`}
            sources={result.sources}
          />
          {result.live && (
            <p className="technical-note">
              Generated from public documentation. Check the sources before
              using the answer.
            </p>
          )}
        </div>
        {liveAvailable ? (
          <form className="ask-form" onSubmit={ask}>
            <label htmlFor="demo-question">
              Ask a question about the project
            </label>
            <textarea
              id="demo-question"
              rows={2}
              maxLength={1000}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={loading}
              aria-describedby="demo-help"
            />
            <div className="ask-form-bottom">
              <span id="demo-help">
                Public demo. Shared daily request limit.
              </span>
              <button
                type="submit"
                className="button primary"
                disabled={loading || !question.trim()}
              >
                {loading ? (
                  <>
                    <LoaderCircle
                      size={15}
                      className="spin"
                      aria-hidden="true"
                    />{" "}
                    Getting answer…
                  </>
                ) : (
                  "Ask question"
                )}
              </button>
            </div>
            {error && (
              <p className="inline-error" role="alert">
                {error}
              </p>
            )}
          </form>
        ) : (
          <p className="demo-unavailable" role="status">
            Live questions are unavailable on this deployment. You can browse
            the sample questions and their sources.
          </p>
        )}
      </div>
    </div>
  );
}
