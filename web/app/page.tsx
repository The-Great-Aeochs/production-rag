import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Playground } from "@/components/playground";
import { repository } from "@/lib/samples";

const roles = [
  ["Visitor", "Try the public demo"],
  ["Member", "Query and read documents in joined workspaces"],
  ["Editor", "Member access, plus refresh a connected source"],
  ["Admin", "Editor access, plus manage members and view access activity"],
];
export default function Home() {
  return (
    <main id="main">
      <section className="hero section-shell" aria-labelledby="intro-title">
        <div>
          <h1 id="intro-title">Document search with cited answers</h1>
          <p className="hero-description">
            Search technical documentation using hybrid retrieval. Inspect the
            source behind an answer, or sign in to work with your team’s
            documents.
          </p>
          <div className="hero-actions">
            <a className="button primary" href="#demo">
              Try the demo <ArrowRight size={16} aria-hidden="true" />
            </a>
            <a className="text-link" href={repository}>
              View on GitHub
            </a>
          </div>
        </div>
        <dl className="project-details">
          <div>
            <dt>Retrieval</dt>
            <dd>Vector search + full-text search</dd>
          </div>
          <div>
            <dt>Sources</dt>
            <dd>Document and section citations</dd>
          </div>
          <div>
            <dt>Access</dt>
            <dd>Permissions for each workspace</dd>
          </div>
        </dl>
      </section>
      <section
        className="section-shell demo-section"
        id="demo"
        aria-labelledby="demo-title"
      >
        <div className="section-heading">
          <h2 id="demo-title">Try a sample question</h2>
          <p>Examples use public project documentation.</p>
        </div>
        <Playground
          liveAvailable={Boolean(
            process.env.RAG_API_URL && process.env.DEMO_PROXY_SECRET,
          )}
        />
      </section>
      <section
        className="section-shell information-section"
        id="architecture"
        aria-labelledby="architecture-title"
      >
        <div className="section-heading">
          <h2 id="architecture-title">How it works</h2>
          <Link className="text-link" href="/docs">
            Read the documentation
          </Link>
        </div>
        <ol className="process-list">
          <li>
            <h3>Index documents</h3>
            <p>
              Split source files into sections and store their text, embeddings,
              and metadata. A durable job queue handles retries.
            </p>
          </li>
          <li>
            <h3>Find relevant sections</h3>
            <p>
              Combine semantic search in Qdrant with full-text search in
              PostgreSQL, then rerank the results.
            </p>
          </li>
          <li>
            <h3>Generate an answer</h3>
            <p>
              Pass the retrieved sections to the model and return the answer
              with source excerpts.
            </p>
          </li>
        </ol>
        <p className="technical-note">
          Built with FastAPI, PostgreSQL, Qdrant, Redis, and S3-compatible
          storage.
        </p>
      </section>
      <section
        className="section-shell information-section"
        id="access"
        aria-labelledby="access-title"
      >
        <div className="section-heading">
          <div>
            <h2 id="access-title">Workspace access</h2>
            <p>
              Members can access documents only in workspaces they belong to.
            </p>
          </div>
          <Link className="text-link" href="/workspace">
            Open a workspace
          </Link>
        </div>
        <table className="permissions-table">
          <caption className="sr-only">Workspace roles and permissions</caption>
          <thead>
            <tr>
              <th scope="col">Role</th>
              <th scope="col">Permissions</th>
            </tr>
          </thead>
          <tbody>
            {roles.map(([role, permission]) => (
              <tr key={role}>
                <th scope="row">{role}</th>
                <td>{permission}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="technical-note">
          Retrieval smoke test: the expected source ranked first for 12
          synthetic questions across six project documents.{" "}
          <a href="/benchmarks/retrieval-smoke.json">
            View results and test scope
          </a>
          .
        </p>
      </section>
      <footer className="site-footer section-shell">
        <span>Production RAG</span>
        <nav aria-label="Footer">
          <Link href="/docs">Documentation</Link>
          <a href={repository}>GitHub</a>
        </nav>
      </footer>
    </main>
  );
}
