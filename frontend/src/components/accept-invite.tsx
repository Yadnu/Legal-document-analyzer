"use client";

import { useOrganizationList } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { acceptInvite } from "@/lib/api";

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

export function AcceptInvite({ token }: { token: string }) {
  const router = useRouter();
  const { setActive } = useOrganizationList();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [joinedName, setJoinedName] = useState<string | null>(null);

  async function onAccept() {
    setPending(true);
    setError(null);
    try {
      const result = await acceptInvite(token);
      setJoinedName(result.workspace_name);
      if (setActive) {
        await setActive({ organization: result.tenant_id });
      }
      router.push("/workspace");
      router.refresh();
    } catch (err) {
      setError(errorDetail(err));
      setPending(false);
    }
  }

  return (
    <div className="card p-8 space-y-5">
      <div>
        <p className="text-xs font-mono text-gold">Shared workspace</p>
        <h1 className="font-display text-2xl font-semibold text-ink mt-2">
          Join this workspace
        </h1>
        <p className="text-sm text-ink-muted mt-2">
          Accepting adds your account to the workspace that sent this invite,
          with the role they chose. You can switch workspaces from the header
          afterward.
        </p>
      </div>
      {joinedName && (
        <p className="text-sm text-ink">Opening {joinedName}…</p>
      )}
      {error && <p className="text-sm text-status-failed">{error}</p>}
      <button
        type="button"
        className="btn-primary"
        onClick={() => void onAccept()}
        disabled={pending}
      >
        {pending ? "Joining…" : "Accept invite"}
      </button>
    </div>
  );
}
