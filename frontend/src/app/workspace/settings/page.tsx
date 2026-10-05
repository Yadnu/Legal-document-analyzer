export const dynamic = "force-dynamic";

import { AuditLogTable } from "@/components/audit-log-table";
import { WorkspaceHeader } from "@/components/workspace-header";
import { WorkspaceMembers } from "@/components/workspace-members";
import { Info, Shield } from "lucide-react";

export const metadata = {
  title: "Settings — Legal Document Navigator",
};

export default function SettingsPage() {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <WorkspaceHeader active="settings" />

      <div className="shrink-0 disclaimer-bar rounded-none border-x-0 border-t-0 px-6 py-1.5">
        <Info size={12} className="text-gold shrink-0" />
        <strong className="text-ink font-medium">Document comprehension only</strong>
        {" — "}this tool helps you understand your documents. It is not legal advice.
      </div>

      <div className="flex-1 overflow-y-auto p-8 max-w-5xl mx-auto w-full">
        {/* Page title */}
        <div className="flex items-center gap-3 mb-8">
          <Shield size={22} className="text-gold" />
          <div>
            <h1 className="font-display text-2xl font-semibold text-ink">
              Settings
            </h1>
            <p className="text-sm text-ink-muted mt-0.5">
              People in this workspace, and the audit trail.
            </p>
          </div>
        </div>

        <section className="mb-12">
          <h2 className="font-display text-base font-semibold text-ink mb-2">
            People
          </h2>
          <p className="text-sm text-ink-muted mb-5">
            Invite teammates into this shared workspace and set what they can do.
            Admins manage membership. Everyone else can see who is here.
          </p>
          <WorkspaceMembers />
        </section>

        {/* Audit log section */}
        <section>
          <h2 className="font-display text-base font-semibold text-ink mb-4">
            Audit Log
          </h2>
          <p className="text-sm text-ink-muted mb-5">
            Immutable record of all significant actions in this workspace.
            Visible to organisation admins only.
          </p>
          <AuditLogTable />
        </section>
      </div>
    </div>
  );
}
