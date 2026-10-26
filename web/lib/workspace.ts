export type Role = "member" | "editor" | "admin";
export type Workspace = { id: string; name: string; role: Role };
export type WorkspaceList = { user_id: string; workspaces: Workspace[] };
export type WorkspaceDocument = {
  source_path: string;
  type: string;
  status: string;
};
export type Member = { user_id: string; role: Role };
export type AuditEvent = {
  actor_id: string;
  target_id: string | null;
  action: string;
  role: Role | null;
  created_at: string;
};
export type WorkspaceView = "chat" | "documents" | "members" | "activity";
export const roleLabels: Record<Role, string> = {
  member: "Member",
  editor: "Editor",
  admin: "Admin",
};
export function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}
