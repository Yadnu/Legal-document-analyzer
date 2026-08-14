export const dynamic = "force-dynamic";

import Link from "next/link";

export default function NotFound() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center gap-4 text-center px-6">
      <h1 className="font-display text-4xl font-semibold text-ink">404</h1>
      <p className="text-ink-muted">Page not found.</p>
      <Link href="/workspace" className="btn-ghost">
        Back to workspace
      </Link>
    </main>
  );
}
