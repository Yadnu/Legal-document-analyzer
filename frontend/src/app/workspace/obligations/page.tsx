export const dynamic = "force-dynamic";

import { Scale, ClipboardList } from "lucide-react";
import { ObligationsDashboard } from "@/components/obligations-dashboard";

export const metadata = {
  title: "Obligations — Legal Document Navigator",
};

export default function ObligationsPage() {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Header */}
      <header className="border-b border-ink-faint/20 bg-surface/80 backdrop-blur-sm shrink-0">
        <div className="px-6 h-14 flex items-center gap-3">
          <Scale size={20} className="text-gold" />
          <span className="font-display text-lg font-semibold text-ink">
            Legal Document Navigator
          </span>
          <nav className="ml-6 flex items-center gap-1 text-sm">
            <a
              href="/workspace"
              className="px-3 py-1 rounded-lg text-ink-muted hover:text-ink hover:bg-surface-card transition-colors"
            >
              Workspace
            </a>
            <a
              href="/workspace/obligations"
              className="px-3 py-1 rounded-lg bg-surface-card text-ink font-medium"
            >
              Obligations
            </a>
            <a
              href="/workspace/settings"
              className="px-3 py-1 rounded-lg text-ink-muted hover:text-ink hover:bg-surface-card transition-colors"
            >
              Settings
            </a>
          </nav>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-8 max-w-5xl mx-auto w-full">
        {/* Page title */}
        <div className="flex items-center gap-3 mb-8">
          <ClipboardList size={22} className="text-gold" />
          <div>
            <h1 className="font-display text-2xl font-semibold text-ink">
              Obligation Tracker
            </h1>
            <p className="text-sm text-ink-muted mt-0.5">
              All contractual obligations and deadlines across your documents.
            </p>
          </div>
        </div>

        <ObligationsDashboard />
      </div>
    </div>
  );
}
