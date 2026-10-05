"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, UserPlus } from "lucide-react";
import { z } from "zod";
import {
  changeMemberRole,
  createInvite,
  getWorkspace,
  removeMember,
  revokeInvite,
} from "@/lib/api";
import type { WorkspaceRole } from "@/lib/types";

const ROLES: { value: WorkspaceRole; label: string; hint: string }[] = [
  { value: "admin", label: "Admin", hint: "Manage people and the audit log" },
  {
    value: "editor",
    label: "Editor",
    hint: "Upload, comment, and ask questions",
  },
  { value: "viewer", label: "Viewer", hint: "Read documents and comments" },
];

const inviteSchema = z.object({
  email: z.string().trim().email("Enter a valid email address."),
  role: z.enum(["admin", "editor", "viewer"]),
});

function errorDetail(err: unknown): string {
  if (!(err instanceof Error)) return "Something went wrong.";
  const raw = err.message.replace(/^\d+:\s*/, "");
  try {
    const parsed = JSON.parse(raw) as { detail?: string };
    if (typeof parsed.detail === "string" && parsed.detail) return parsed.detail;
  } catch {
    // Body was not JSON.
  }
  return raw || "Something went wrong.";
}

function formatWhen(iso: string) {
  try {
    return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
  } catch {
    return iso;
  }
}

export function WorkspaceMembers() {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<WorkspaceRole>("editor");
  const [formError, setFormError] = useState<string | null>(null);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["workspace"],
    queryFn: getWorkspace,
  });

  function refresh() {
    return queryClient.invalidateQueries({ queryKey: ["workspace"] });
  }

  const invite = useMutation({
    mutationFn: createInvite,
    onSuccess: async (created) => {
      setEmail("");
      setInviteUrl(created.invite_url ?? null);
      setFormError(null);
      await refresh();
    },
    onError: (err) => setFormError(errorDetail(err)),
  });

  const changeRole = useMutation({
    mutationFn: ({ userId, next }: { userId: string; next: WorkspaceRole }) =>
      changeMemberRole(userId, next),
    onSuccess: () => refresh(),
    onError: (err) => setFormError(errorDetail(err)),
  });

  const revoke = useMutation({
    mutationFn: revokeInvite,
    onSuccess: () => refresh(),
    onError: (err) => setFormError(errorDetail(err)),
  });

  const remove = useMutation({
    mutationFn: removeMember,
    onSuccess: async () => {
      setConfirmRemove(null);
      await refresh();
    },
    onError: (err) => setFormError(errorDetail(err)),
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-ink-muted py-8">
        <Loader2 size={16} className="animate-spin" />
        Loading people…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <p className="text-sm text-status-failed">
        {errorDetail(error)}
      </p>
    );
  }

  const canManage = data.caller_role === "admin";
  const seatsFull = data.seat_count >= data.max_members;

  function onInvite(event: React.FormEvent) {
    event.preventDefault();
    const parsed = inviteSchema.safeParse({ email, role });
    if (!parsed.success) {
      setFormError(parsed.error.issues[0]?.message ?? "Check the invite.");
      return;
    }
    setFormError(null);
    invite.mutate(parsed.data);
  }

  return (
    <div className="space-y-8">
      <p className="text-sm text-ink-muted">
        {data.seat_count} of {data.max_members} seats used in {data.name}.
        Pending invites count toward the limit.
      </p>

      {canManage && (
        <form onSubmit={onInvite} className="card p-5 space-y-4">
          <div className="flex items-center gap-2">
            <UserPlus size={16} className="text-gold" />
            <h3 className="font-display text-base font-semibold text-ink">
              Invite a teammate
            </h3>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="block text-sm flex-1">
              <span className="text-ink-muted text-xs">Email</span>
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="colleague@firm.com"
                className="mt-1 w-full rounded-lg border border-ink-faint/30 bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:ring-1 focus:ring-gold/60"
              />
            </label>
            <label className="block text-sm">
              <span className="text-ink-muted text-xs">Role</span>
              <select
                value={role}
                onChange={(event) => setRole(event.target.value as WorkspaceRole)}
                className="mt-1 w-full rounded-lg border border-ink-faint/30 bg-surface px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-gold/60"
              >
                {ROLES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="submit"
              className="btn-primary"
              disabled={invite.isPending || seatsFull}
            >
              {invite.isPending ? "Sending…" : "Send invite"}
            </button>
          </div>
          <p className="text-xs text-ink-muted">
            {ROLES.find((item) => item.value === role)?.hint}
          </p>
          {seatsFull && (
            <p className="text-sm text-status-failed">
              This workspace is at its member limit.
            </p>
          )}
          {formError && <p className="text-sm text-status-failed">{formError}</p>}
          {inviteUrl && (
            <label className="block text-sm">
              <span className="text-ink-muted text-xs">
                Invite link — share it if email delivery is off
              </span>
              <input
                readOnly
                value={inviteUrl}
                onFocus={(event) => event.currentTarget.select()}
                className="mt-1 w-full rounded-lg border border-ink-faint/30 bg-surface px-3 py-1.5 text-xs font-mono text-ink focus:outline-none focus:ring-1 focus:ring-gold/60"
              />
            </label>
          )}
        </form>
      )}

      <section>
        <h3 className="font-display text-base font-semibold text-ink mb-3">
          Members
        </h3>
        <div className="rounded-xl border border-ink-faint/20 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-surface-card border-b border-ink-faint/20">
                <th className="px-4 py-2.5 text-left font-medium text-ink-muted">
                  Person
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-ink-muted">
                  Role
                </th>
                <th className="px-4 py-2.5 text-left font-medium text-ink-muted">
                  Joined
                </th>
                {canManage && <th className="px-4 py-2.5" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-faint/10">
              {data.members.map((member) => (
                <tr key={member.user_id}>
                  <td className="px-4 py-2.5">
                    <div className="text-ink">{member.full_name ?? member.email}</div>
                    {member.full_name && (
                      <div className="text-xs text-ink-muted">{member.email}</div>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    {canManage ? (
                      <select
                        aria-label={`Role for ${member.email}`}
                        value={member.role}
                        disabled={changeRole.isPending}
                        onChange={(event) =>
                          changeRole.mutate({
                            userId: member.user_id,
                            next: event.target.value as WorkspaceRole,
                          })
                        }
                        className="rounded-lg border border-ink-faint/30 bg-surface px-2 py-1 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-gold/60"
                      >
                        {ROLES.map((item) => (
                          <option key={item.value} value={item.value}>
                            {item.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="status-badge bg-surface-card text-ink-muted border border-ink-faint/20 capitalize">
                        {member.role}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-ink-muted font-mono text-xs">
                    {formatWhen(member.created_at)}
                  </td>
                  {canManage && (
                    <td className="px-4 py-2.5 text-right">
                      {confirmRemove === member.user_id ? (
                        <span className="inline-flex gap-2">
                          <button
                            type="button"
                            className="btn-ghost px-2 py-1 text-status-failed"
                            onClick={() => remove.mutate(member.user_id)}
                            disabled={remove.isPending}
                          >
                            Confirm remove
                          </button>
                          <button
                            type="button"
                            className="btn-ghost px-2 py-1"
                            onClick={() => setConfirmRemove(null)}
                          >
                            Cancel
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          className="btn-ghost px-2 py-1"
                          onClick={() => setConfirmRemove(member.user_id)}
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h3 className="font-display text-base font-semibold text-ink mb-3">
          Pending invites
        </h3>
        {data.invites.length === 0 ? (
          <p className="text-sm text-ink-muted">No pending invites.</p>
        ) : (
          <ul className="rounded-xl border border-ink-faint/20 divide-y divide-ink-faint/10">
            {data.invites.map((item) => (
              <li
                key={item.id}
                className="px-4 py-3 flex items-center gap-3 text-sm"
              >
                <span className="text-ink">{item.email}</span>
                <span className="status-badge bg-gold/10 text-gold border border-gold/25 capitalize">
                  {item.role}
                </span>
                <span className="text-xs text-ink-muted font-mono ml-auto">
                  Expires {formatWhen(item.expires_at)}
                </span>
                {canManage && (
                  <button
                    type="button"
                    className="btn-ghost px-2 py-1"
                    onClick={() => revoke.mutate(item.id)}
                    disabled={revoke.isPending}
                  >
                    Revoke
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
