import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  Database,
  FileText,
  GitBranch,
  KeyRound,
  Layers3,
  LockKeyhole,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Playground } from "@/components/playground";
import { Mark } from "@/components/nav";
import { repository } from "@/lib/samples";
const stages = [
  {
    icon: FileText,
    title: "Understand the source",
    label: "01 / INGEST",
    text: "Documents become structural chunks, with their origin and section intact.",
  },
  {
    icon: Search,
    title: "Search both ways",
    label: "02 / RETRIEVE",
    text: "Vector meaning meets exact keyword search. Results are fused, then reranked.",
  },
  {
    icon: Sparkles,
    title: "Answer with evidence",
    label: "03 / GENERATE",
    text: "Relevant context goes to the model. Sources come back with the answer.",
  },
];
export default function Home() {
  return (
    <main id="main">
      <section className="hero section-shell">
        <div className="hero-copy">
          <p className="eyebrow">
            <span className="status-dot live" /> AN ENGINEERING PROJECT, OPEN TO
            EXPLORE
          </p>
          <h1>
            Answers with
            <br />a <em>paper trail.</em>
          </h1>
          <p className="hero-description">
            A retrieval system that shows its work. Hybrid search, cited
            answers, and access control—built from the ground up.
          </p>
          <div className="hero-actions">
            <a className="button primary" href="#demo">
              Explore the playground <ArrowRight size={17} />
            </a>
            <a
              className="text-link"
              href={repository}
              target="_blank"
              rel="noreferrer"
            >
              Read the source <ArrowUpRight size={15} />
            </a>
          </div>
          <div className="hero-caption">
            <span className="caption-rule" /> No orchestration framework. Every
            step is inspectable.
          </div>
        </div>
        <div
          className="hero-diagram"
          aria-label="A question flows through hybrid retrieval into a cited answer"
        >
          <div className="diagram-topline">
            <span>SYSTEM IN MINIATURE</span>
            <span>QUERY → EVIDENCE → ANSWER</span>
          </div>
          <div className="diagram-question">
            <span className="diagram-q">?</span>
            <span>What happens when a worker fails?</span>
            <ArrowUpRight size={15} />
          </div>
          <div className="diagram-stem" />
          <div className="diagram-searches">
            <div>
              <Database size={19} />
              <span>
                Semantic search<small>QDRANT</small>
              </span>
              <span className="diagram-light" />
            </div>
            <div>
              <Search size={19} />
              <span>
                Keyword search<small>POSTGRESQL</small>
              </span>
              <span className="diagram-light" />
            </div>
          </div>
          <div className="diagram-join">
            <i />
            <span>FUSE + RERANK</span>
            <i />
          </div>
          <div className="diagram-answer">
            <div>
              <Sparkles size={17} />
              <strong>The job stays in the queue.</strong>
            </div>
            <p>A new worker can retry it once the corpus lock is released.</p>
            <span className="mini-citation">
              <BookOpen size={12} /> ingestion.md <ArrowUpRight size={11} />
            </span>
          </div>
          <div className="diagram-bottomline">
            <ShieldCheck size={13} /> Scoped retrieval. Traceable sources.
          </div>
          <span className="diagram-decoration d-one">+</span>
          <span className="diagram-decoration d-two">+</span>
        </div>
      </section>
      <div className="stack-strip">
        <div className="section-shell">
          <span className="stack-label">UNDER THE HOOD</span>
          <span>FastAPI</span>
          <span>Qdrant</span>
          <span>PostgreSQL</span>
          <span>Redis</span>
          <span>S3-compatible storage</span>
        </div>
      </div>
      <section className="section-shell demo-section" id="demo">
        <div className="section-heading">
          <div>
            <p className="eyebrow">01 / SEE IT IN CONTEXT</p>
            <h2>
              Follow the question.
              <br />
              <em>Check the source.</em>
            </h2>
          </div>
          <p>
            Start with a guided example. When live inference is connected, ask
            your own question against the same public corpus.
          </p>
        </div>
        <Playground
          liveAvailable={Boolean(
            process.env.RAG_API_URL && process.env.DEMO_PROXY_SECRET,
          )}
        />
      </section>
      <section className="architecture-section" id="architecture">
        <div className="section-shell">
          <div className="section-heading">
            <div>
              <p className="eyebrow">02 / THE PARTS THAT MATTER</p>
              <h2>
                A small system.
                <br />
                <em>Deliberate boundaries.</em>
              </h2>
            </div>
            <Link href="/docs" className="text-link">
              Walk through the architecture <ArrowUpRight size={16} />
            </Link>
          </div>
          <div className="stage-grid">
            {stages.map((stage) => (
              <article key={stage.label} className="stage">
                <div className="stage-top">
                  <stage.icon size={22} />
                  <span>{stage.label}</span>
                </div>
                <h3>{stage.title}</h3>
                <p>{stage.text}</p>
              </article>
            ))}
          </div>
          <div className="recovery-callout">
            <div className="recovery-icon">
              <GitBranch size={23} />
            </div>
            <div>
              <h3>Failure is part of the design.</h3>
              <p>
                Durable jobs, retryable publication, and versioned cache keys
                keep partial failures from becoming silent inconsistencies.
              </p>
            </div>
            <Link href="/docs#recovery" aria-label="Read about recovery">
              <ArrowUpRight size={22} />
            </Link>
          </div>
        </div>
      </section>
      <section className="section-shell access-section" id="access">
        <div className="access-copy">
          <p className="eyebrow">
            03 / THE RIGHT CONTEXT, FOR THE RIGHT PERSON
          </p>
          <h2>
            Access follows
            <br />
            <em>the workspace.</em>
          </h2>
          <p>
            Workspace memberships determine what each person can do. The backend
            checks permissions on every request, and search stays inside the
            chosen workspace.
          </p>
          <ul className="check-list">
            <li>
              <Check size={16} /> Signed login tokens, verified server-side
            </li>
            <li>
              <Check size={16} /> Roles stored in the database
            </li>
            <li>
              <Check size={16} /> Versioned access and an audit trail
            </li>
          </ul>
          <Link href="/workspace" className="button secondary">
            Open your workspace <ArrowRight size={16} />
          </Link>
        </div>
        <div className="role-table">
          <div className="role-table-title">
            <LockKeyhole size={16} />
            <span>WORKSPACE PERMISSIONS</span>
          </div>
          <div className="role-row">
            <span className="role-icon">
              <BookOpen size={17} />
            </span>
            <div>
              <strong>Visitor</strong>
              <p>Explore the public sample corpus</p>
            </div>
            <span className="role-tag">PUBLIC</span>
          </div>
          <div className="role-row">
            <span className="role-icon">
              <Search size={17} />
            </span>
            <div>
              <strong>Member</strong>
              <p>Ask questions and read workspace documents</p>
            </div>
          </div>
          <div className="role-row">
            <span className="role-icon">
              <Layers3 size={17} />
            </span>
            <div>
              <strong>Editor</strong>
              <p>Refresh the connected document source</p>
            </div>
          </div>
          <div className="role-row">
            <span className="role-icon">
              <KeyRound size={17} />
            </span>
            <div>
              <strong>Admin</strong>
              <p>Manage members, roles, and access</p>
            </div>
            <span className="role-tag orange">PRIVILEGED</span>
          </div>
          <div className="role-table-foot">
            <ShieldCheck size={14} /> Membership checks apply to API calls, too.
          </div>
        </div>
      </section>
      <section className="evidence-section">
        <div className="section-shell evidence-grid">
          <div>
            <p className="eyebrow">04 / MEASURE, THEN MAKE CLAIMS</p>
            <h2>
              A benchmark with
              <br />
              <em>its scope attached.</em>
            </h2>
            <p>
              The initial retrieval smoke test uses six small project documents
              and twelve questions. It checks the pipeline—not production
              capacity or customer-domain quality.
            </p>
            <a
              className="text-link"
              href="/benchmarks/retrieval-smoke.json"
              target="_blank"
              rel="noreferrer"
            >
              Inspect the evaluation <ArrowUpRight size={15} />
            </a>
          </div>
          <div className="evidence-stats">
            <div>
              <strong>
                12<span>/12</span>
              </strong>
              <p>Expected source ranked first</p>
            </div>
            <div className="evidence-detail">
              <span>MODEL</span>
              <p>BGE-base + MiniLM reranker</p>
              <span>SETUP</span>
              <p>CPU · PostgreSQL · Qdrant local</p>
              <span>DATASET</span>
              <p>Synthetic project smoke test</p>
            </div>
          </div>
        </div>
      </section>
      <footer className="site-footer section-shell">
        <Link href="/" aria-label="Production RAG home">
          <Mark />
        </Link>
        <p>Built to be understood. Designed to be checked.</p>
        <a href={repository} target="_blank" rel="noreferrer">
          <GitBranch size={16} /> GitHub <ArrowUpRight size={13} />
        </a>
      </footer>
    </main>
  );
}
