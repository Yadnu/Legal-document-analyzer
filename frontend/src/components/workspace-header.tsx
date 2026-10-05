"use client";

import { useOrganization, useOrganizationList } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { Scale } from "lucide-react";
import type { ReactNode } from "react";

const LINKS = [
  { href: "/workspace", id: "workspace", label: "Workspace" },
  { href: "/workspace/obligations", id: "obligations", label: "Obligations" },
  { href: "/workspace/settings", id: "settings", label: "Settings" },
] as const;

type NavId = (typeof LINKS)[number]["id"];

export function WorkspaceHeader({
  active,
  trailing,
}: {
  active: NavId;
  trailing?: ReactNode;
}) {
  return (
    <header className="border-b border-ink-faint/20 bg-surface/80 backdrop-blur-sm shrink-0">
      <div className="px-6 h-14 flex items-center gap-3">
        <Scale size={20} className="text-gold shrink-0" />
        <span className="font-display text-lg font-semibold text-ink">
          Legal Document Navigator
        </span>
        <nav className="ml-6 flex items-center gap-1 text-sm">
          {LINKS.map((link) => (
            <a
              key={link.id}
              href={link.href}
              className={
                link.id === active
                  ? "px-3 py-1 rounded-lg bg-surface-card text-ink font-medium"
                  : "px-3 py-1 rounded-lg text-ink-muted hover:text-ink hover:bg-surface-card transition-colors"
              }
            >
              {link.label}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <WorkspaceSwitcher />
          {trailing}
        </div>
      </div>
    </header>
  );
}

function WorkspaceSwitcher() {
  const router = useRouter();
  const { organization } = useOrganization();
  const { isLoaded, setActive, userMemberships } = useOrganizationList({
    userMemberships: { infinite: true },
  });

  if (!isLoaded || !setActive) return null;
  const memberships = userMemberships.data ?? [];
  if (memberships.length === 0) return null;
  if (memberships.length === 1) {
    return (
      <span className="text-sm text-ink-muted truncate max-w-xs">
        {memberships[0].organization.name}
      </span>
    );
  }

  return (
    <select
      aria-label="Workspace"
      className="max-w-xs rounded-lg border border-ink-faint/30 bg-surface-card px-2 py-1 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-gold/60"
      value={organization?.id ?? ""}
      onChange={(event) => {
        const organizationId = event.target.value;
        if (!organizationId) return;
        void setActive({ organization: organizationId }).then(() => {
          router.refresh();
        });
      }}
    >
      {memberships.map((membership) => (
        <option key={membership.id} value={membership.organization.id}>
          {membership.organization.name}
        </option>
      ))}
    </select>
  );
}
