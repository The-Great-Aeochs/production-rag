import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { repository } from "@/lib/samples";
export const metadata = { title: "Documentation" };
export default function Docs() {
  return (
    <main id="main" className="page-shell docs-page">
      <h1>Documentation</h1>
      <p>
        How documents are indexed, searched, and restricted to the right
        workspace.
      </p>
      <a
        href={`${repository}/tree/main/docs`}
        className="text-link"
        target="_blank"
        rel="noreferrer"
      >
        Read the technical guides <ArrowUpRight size={15} />
      </a>
      <h2>The query path</h2>
      <ol>
        <li>
          <strong>Authenticate and scope.</strong> The backend verifies a bearer
          token. Logged-in users select a workspace they belong to; role claims
          from the browser do not grant access.
        </li>
        <li>
          <strong>Load context.</strong> A conversation belongs to its creator
          and workspace. Concurrent turns are serialized. Conversation answers
          bypass the shared response cache.
        </li>
        <li>
          <strong>Retrieve.</strong> Semantic search in Qdrant and full-text
          search in Postgres run in parallel, with the same corpus and metadata
          filters.
        </li>
        <li>
          <strong>Fuse and rerank.</strong> Reciprocal Rank Fusion combines the
          lists. A cross-encoder rescores the candidates.
        </li>
        <li>
          <strong>Generate.</strong> The model receives the selected context.
          The interface streams the answer and exposes source excerpts for
          inspection.
        </li>
      </ol>
      <h2 id="recovery">Recoverable ingestion</h2>
      <p>
        Accepted jobs live in Postgres. Workers hold a corpus advisory lock
        while processing. If a worker exits, its connection releases the lock
        and another worker can retry.
      </p>
      <p>
        A document is marked pending before external writes begin. It becomes
        visible after Qdrant and object storage acknowledge the writes.
        Deletions keep a tombstone until cleanup succeeds. This is a recoverable
        publication process, not a transaction spanning three databases.
      </p>
      <h2>Workspace access</h2>
      <p>
        Members can query and read their workspace documents. Editors can
        refresh an existing connected source. Admins can manage membership and
        inspect access activity. Changes increment a membership version,
        invalidating the affected user’s earlier cache/session namespace on
        subsequent requests.
      </p>
      <p>
        Workspaces are created with server-generated IDs. Creating your own
        workspace never grants access to another corpus. The last admin cannot
        be removed or demoted.
      </p>
      <h2>What the public demo does</h2>
      <p>
        Sample answers are prewritten and are labeled that way. When live
        inference is connected, public questions use only a dedicated sample
        corpus, with global per-minute and per-day limits. The public demo has
        no private workspace sessions.
      </p>
      <h2>Deploy the website</h2>
      <p>
        Connect this repository to Vercel and set its Root Directory to{" "}
        <code>web</code>. The showcase builds without account credentials. Login
        and live inference require additional configuration; they fail closed
        while it is missing.
      </p>
      <pre>
        <code>{`cd web\nnpm ci\ncp .env.example .env.local\nnpm run dev`}</code>
      </pre>
      <p>
        Configure Clerk, the trusted backend issuer/audience, and your FastAPI
        deployment using the repository’s{" "}
        <a
          href={`${repository}/blob/main/docs/website.md`}
          target="_blank"
          rel="noreferrer"
        >
          website deployment guide
        </a>
        . Never expose the backend admin key to a browser.
      </p>
      <Link className="button primary" href="/#demo">
        Back to the demo
      </Link>
    </main>
  );
}
