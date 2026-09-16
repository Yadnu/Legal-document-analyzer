import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

interface Params {
  params: Promise<{ docId: string; chunkId: string }>;
}

export async function GET(
  _req: NextRequest,
  { params }: Params
): Promise<NextResponse> {
  const { docId, chunkId } = await params;
  const res = await backendFetch(
    `/api/v1/documents/${docId}/chunks/${chunkId}/comments`
  );
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function POST(
  req: NextRequest,
  { params }: Params
): Promise<NextResponse> {
  const { docId, chunkId } = await params;
  const body: unknown = await req.json();
  const res = await backendFetch(
    `/api/v1/documents/${docId}/chunks/${chunkId}/comments`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}
