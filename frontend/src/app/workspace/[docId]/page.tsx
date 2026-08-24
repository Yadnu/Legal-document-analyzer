export const dynamic = "force-dynamic";

import { DocLayout } from "@/components/doc-layout";
import type { CitationOut } from "@/lib/types";

interface PageProps {
  params: Promise<{ docId: string }>;
  searchParams: Promise<{ chunk?: string; quote?: string }>;
}

export async function generateMetadata({ params }: PageProps) {
  const { docId } = await params;
  return { title: `Document ${docId.slice(0, 8)}… — Legal Document Navigator` };
}

export default async function DocumentPage({
  params,
  searchParams,
}: PageProps) {
  const { docId } = await params;
  const { chunk, quote } = await searchParams;

  // Build an initial citation from URL params so clicking a workspace citation
  // opens this page with the referenced clause already highlighted.
  const initialCitation: CitationOut | undefined =
    chunk
      ? {
          document_id: docId,
          chunk_id: chunk,
          section: null,
          quote: quote ?? "",
        }
      : undefined;

  return <DocLayout documentId={docId} initialCitation={initialCitation} />;
}
