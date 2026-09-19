import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

interface Params {
  params: Promise<{ docId: string }>;
}

/** POST /api/documents/[docId]/obligations/extract — trigger Bedrock extraction */
export async function POST(
  _req: NextRequest,
  { params }: Params
): Promise<NextResponse> {
  const { docId } = await params;
  const res = await backendFetch(
    `/api/v1/documents/${docId}/obligations/extract`,
    { method: "POST", headers: { "Content-Type": "application/json" } }
  );
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}
