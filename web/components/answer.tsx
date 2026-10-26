"use client";
import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { Source } from "@/lib/sse";

export function AnswerMarkdown({ children }: { children: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown skipHtml components={{ img: () => null }}>
        {children}
      </ReactMarkdown>
    </div>
  );
}

export function Sources({ sources }: { sources: Source[] }) {
  const id = useId();
  const [expanded, setExpanded] = useState<number | null>(null);
  if (!sources.length) return null;
  return (
    <div className="source-list" aria-label="Answer sources">
      {sources.map((source, index) => (
        <div className="source-item" key={`${source.source_path}-${index}`}>
          <button
            type="button"
            className="source-toggle"
            aria-expanded={expanded === index}
            aria-controls={`${id}-${index}`}
            onClick={() => setExpanded(expanded === index ? null : index)}
          >
            View source: {source.source_path}
            <ChevronDown size={15} aria-hidden="true" />
          </button>
          <div
            className="source-preview"
            id={`${id}-${index}`}
            hidden={expanded !== index}
          >
            {source.section_path?.length ? (
              <p className="source-section">
                {source.section_path.join(" / ")}
              </p>
            ) : null}
            <p>{source.content || "Source excerpt is unavailable."}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
