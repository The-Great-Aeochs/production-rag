import { roleLabels, type AuditEvent } from "@/lib/workspace";
const actions: Record<string, string> = {
  "workspace.created": "Workspace created",
  "member.assigned": "Member role updated",
  "member.revoked": "Member access removed",
  "documents.synced": "Document refresh requested",
};
export function ActivityPanel({
  events,
  loading,
}: {
  events: AuditEvent[];
  loading: boolean;
}) {
  return (
    <section className="workspace-panel" aria-labelledby="activity-title">
      <div className="panel-heading">
        <div>
          <h2 id="activity-title">Access activity</h2>
          <p>Recent membership changes and source refreshes.</p>
        </div>
      </div>
      {!events.length && !loading && <p>No activity to display.</p>}
      <ol className="audit-list">
        {events.map((event, index) => (
          <li key={index}>
            <div>
              <strong>{actions[event.action] || event.action}</strong>
              <p>
                {event.target_id || event.actor_id}
                {event.role ? ` · ${roleLabels[event.role]}` : ""}
              </p>
            </div>
            <time dateTime={event.created_at}>
              {new Date(event.created_at).toLocaleString()}
            </time>
          </li>
        ))}
      </ol>
    </section>
  );
}
