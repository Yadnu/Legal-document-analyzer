export const dynamic = "force-dynamic";

import { DocumentList } from "@/components/document-list";
import { WorkspaceChat } from "@/components/workspace-chat";
import { QuotaBar } from "@/components/quota-bar";
import { Scale, Info } from "lucide-react";

export const metadata = {
  title: "Workspace — Legal Document Navigator",
};

export default function WorkspacePage() {
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
              className="px-3 py-1 rounded-lg bg-surface-card text-ink font-medium"
            >
              Workspace
            </a>
            <a
              href="/workspace/obligations"
              className="px-3 py-1 rounded-lg text-ink-muted hover:text-ink hover:bg-surface-card transition-colors"
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
          <div className="ml-auto">
            <QuotaBar />
          </div>
        </div>
      </header>

      {/* Disclaimer */}
      <div className="shrink-0 disclaimer-bar rounded-none border-x-0 border-t-0 px-6 py-1.5">
        <Info size={12} className="text-gold shrink-0" />
        <strong className="text-ink font-medium">Document comprehension only</strong>
        {" — "}this tool helps you understand your documents. It is not legal advice.
        Consult a qualified attorney for legal guidance.
      </div>

      {/* Two-column body */}
      <div className="flex-1 min-h-0 grid grid-cols-[380px_1fr] gap-0 overflow-hidden">
        {/* Left: document list */}
        <div className="flex flex-col overflow-hidden border-r border-surface-card">
          <div className="px-5 pt-5 pb-3 shrink-0">
            <h2 className="font-display text-base font-semibold text-ink">
              Documents
            </h2>
            <p className="text-xs text-ink-muted mt-0.5">
              Your uploaded contracts and policies.
            </p>
          </div>
          <div className="flex-1 overflow-y-auto px-4 pb-4">
            <DocumentList />
          </div>
        </div>

        {/* Right: workspace Q&A */}
        <div className="flex flex-col overflow-hidden p-5">
          <WorkspaceChat />
        </div>
      </div>
    </div>
  );
}
