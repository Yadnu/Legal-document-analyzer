export const dynamic = "force-dynamic";

import { DocLayout } from "@/components/doc-layout";

interface PageProps {
  params: Promise<{ docId: string }>;
}

export async function generateMetadata({ params }: PageProps) {
  const { docId } = await params;
  return { title: `Document ${docId.slice(0, 8)}… — Legal Document Navigator` };
}

export default async function DocumentPage({ params }: PageProps) {
  const { docId } = await params;
  return <DocLayout documentId={docId} />;
}
