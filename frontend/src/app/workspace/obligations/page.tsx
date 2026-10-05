export const dynamic = "force-dynamic";

import { WorkspaceHeader } from "@/components/workspace-header";
import { Info, ClipboardList } from "lucide-react";
import { ObligationsDashboard } from "@/components/obligations-dashboard";

export const metadata = {
  title: "Obligations — Legal Document Navigator",
};

export default function ObligationsPage() {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <WorkspaceHeader active="obligations" />

      <div className="shrink-0 disclaimer-bar rounded-none border-x-0 border-t-0 px-6 py-1.5">
        <Info size={12} className="text-gold shrink-0" />
        <strong className="text-ink font-medium">Document comprehension only</strong>
        {" — "}this tool helps you understand your documents. It is not legal advice.
      </div>

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
