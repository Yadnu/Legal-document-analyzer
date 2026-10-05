export const dynamic = "force-dynamic";

import { AcceptInvite } from "@/components/accept-invite";
import { Info, Scale } from "lucide-react";

export const metadata = {
  title: "Join workspace — Legal Document Navigator",
};

interface PageProps {
  params: Promise<{ token: string }>;
}

export default async function InvitePage({ params }: PageProps) {
  const { token } = await params;
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-ink-faint/20 bg-surface/80 backdrop-blur-sm">
        <div className="px-6 h-14 flex items-center gap-3">
          <Scale size={20} className="text-gold" />
          <span className="font-display text-lg font-semibold text-ink">
            Legal Document Navigator
          </span>
        </div>
      </header>
      <main className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-lg space-y-4">
          <AcceptInvite token={token} />
          <div className="disclaimer-bar">
            <Info size={12} className="text-gold shrink-0" />
            <span>
              <strong className="text-ink font-medium">
                Document comprehension only
              </strong>
              {" — "}
              this tool helps you understand your documents. It is not legal
              advice.
            </span>
          </div>
        </div>
      </main>
    </div>
  );
}
