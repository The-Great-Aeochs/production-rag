import type { WorkspaceDocument } from "@/lib/workspace";
export function DocumentsPanel({
  documents,
  canEdit,
  busy,
  onSync,
}: {
  documents: WorkspaceDocument[];
  canEdit: boolean;
  busy: boolean;
  onSync: () => void;
}) {
  return (
    <section className="workspace-panel" aria-labelledby="documents-title">
      <div className="panel-heading">
        <div>
          <h2 id="documents-title">Documents</h2>
          <p>Sources connected to this workspace.</p>
        </div>
        {canEdit && (
          <button className="button secondary" onClick={onSync} disabled={busy}>
            Refresh source
          </button>
        )}
      </div>
      {documents.length ? (
        <table className="document-table">
          <caption className="sr-only">Connected documents</caption>
          <thead>
            <tr>
              <th scope="col">Document</th>
              <th scope="col">Type</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((doc) => (
              <tr key={doc.source_path}>
                <th scope="row">{doc.source_path}</th>
                <td>{doc.type}</td>
                <td>{doc.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="empty-small">
          <h3>No documents connected</h3>
          <p>
            Ask a workspace administrator to connect a document source. File
            uploads are not available.
          </p>
        </div>
      )}
    </section>
  );
}
