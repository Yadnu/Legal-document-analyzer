export const dynamic = "force-dynamic";

import { AuditLogTable } from "@/components/audit-log-table";
import { Scale, Shield } from "lucide-react";

export const metadata = {
  title: "Settings — Legal Document Navigator",
};

export default function SettingsPage() {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Header */}
      <header className="border-b border-ink-faint/20 bg-surface/80 backdrop-blur-sm shrink-0">
        <div className="px-6 h-14 flex items-center gap-3">
          <Scale size={20} className="text-gold" />
          <span className="font-display text-lg font-semibold text-ink">
            Legal Document Navigator
          </span>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-8 max-w-5xl mx-auto w-full">
        {/* Page title */}
        <div className="flex items-center gap-3 mb-8">
          <Shield size={22} className="text-gold" />
          <div>
            <h1 className="font-display text-2xl font-semibold text-ink">
              Settings
            </h1>
            <p className="text-sm text-ink-muted mt-0.5">
              Workspace configuration and audit trail.
            </p>
          </div>
        </div>

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
