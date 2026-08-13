export const dynamic = "force-dynamic";

import { DocumentList } from "@/components/document-list";
import { Scale, Info } from "lucide-react";

export const metadata = {
  title: "Workspace — Legal Document Navigator",
};

export default function WorkspacePage() {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-ink-faint/20 bg-surface/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-6 h-14 flex items-center gap-3">
          <Scale size={20} className="text-gold" />
          <span className="font-display text-lg font-semibold text-ink">
            Legal Document Navigator
          </span>
        </div>
      </header>

      <main className="flex-1 max-w-5xl mx-auto w-full px-6 py-10 flex flex-col gap-8">
        {/* Disclaimer */}
        <div className="disclaimer-bar">
          <Info size={13} className="text-gold shrink-0" />
          <span>
            <strong className="text-ink font-medium">Document comprehension only</strong>
            {" — "}this tool helps you understand your documents. It is not legal advice.
            Consult a qualified attorney for legal guidance.
          </span>
        </div>

        {/* Hero */}
        <div className="flex flex-col gap-2">
          <h1 className="font-display text-3xl font-semibold text-ink">
            Your workspace
          </h1>
          <p className="text-ink-muted text-sm">
            Upload contracts, leases, or policies — then ask questions and get
            clause-cited answers.
          </p>
        </div>

        <DocumentList />
      </main>
    </div>
  );
}
