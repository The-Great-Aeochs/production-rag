"use client";
import { useState } from "react";
import { roleLabels, type Member, type Role } from "@/lib/workspace";
const roles = Object.entries(roleLabels) as [Role, string][];
export function MembersPanel({
  members,
  userId,
  busy,
  onChange,
}: {
  members: Member[];
  userId: string;
  busy: boolean;
  onChange: (id: string, role: Role | null) => Promise<boolean>;
}) {
  const [newMember, setNewMember] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [removing, setRemoving] = useState<string | null>(null);
  return (
    <section className="workspace-panel" aria-labelledby="members-title">
      <div className="panel-heading">
        <div>
          <h2 id="members-title">Members</h2>
          <p>Roles apply to this workspace. At least one admin must remain.</p>
        </div>
      </div>
      <form
        className="member-form"
        onSubmit={async (event) => {
          event.preventDefault();
          if (await onChange(newMember.trim(), role)) setNewMember("");
        }}
      >
        <label htmlFor="member-id">Add a teammate by workspace user ID</label>
        <p id="member-help">
          They can copy their ID from the workspace sidebar after signing in.
        </p>
        <div>
          <input
            id="member-id"
            value={newMember}
            onChange={(e) => setNewMember(e.target.value)}
            pattern="usr_[a-f0-9]{64}"
            required
            aria-describedby="member-help"
          />
          <select
            aria-label="New member role"
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
          >
            {roles.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <button
            className="button primary"
            disabled={busy || !newMember.trim()}
            type="submit"
          >
            Add member
          </button>
        </div>
      </form>
      <ul className="member-list">
        {members.map((member) => (
          <li key={member.user_id}>
            <code>
              {member.user_id}
              {member.user_id === userId ? " (you)" : ""}
            </code>
            <MemberRoleEditor
              key={`${member.user_id}-${member.role}`}
              member={member}
              busy={busy}
              onChange={onChange}
            />
            <button
              type="button"
              className="revoke-button"
              onClick={() => setRemoving(member.user_id)}
              disabled={busy}
            >
              Remove
            </button>
            {removing === member.user_id && (
              <div className="removal-confirmation">
                <p>Remove this member’s workspace access?</p>
                <button
                  className="button danger"
                  disabled={busy}
                  onClick={async () => {
                    if (await onChange(member.user_id, null)) setRemoving(null);
                  }}
                >
                  Remove member
                </button>
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => setRemoving(null)}
                >
                  Cancel
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function MemberRoleEditor({
  member,
  busy,
  onChange,
}: {
  member: Member;
  busy: boolean;
  onChange: (id: string, role: Role | null) => Promise<boolean>;
}) {
  const [role, setRole] = useState(member.role);
  return (
    <form
      className="member-role-editor"
      onSubmit={(event) => {
        event.preventDefault();
        if (!busy && role !== member.role) void onChange(member.user_id, role);
      }}
    >
      <select
        aria-label={`Role for ${member.user_id}`}
        value={role}
        disabled={busy}
        onChange={(event) => setRole(event.target.value as Role)}
      >
        {roles.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <button
        type="submit"
        className="button secondary"
        disabled={busy || role === member.role}
      >
        Save role
      </button>
    </form>
  );
}
