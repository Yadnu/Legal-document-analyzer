import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

interface Params {
  params: Promise<{ docId: string }>;
}

/** GET /api/documents/[docId]/obligations */
export async function GET(
  req: NextRequest,
  { params }: Params
): Promise<NextResponse> {
  const { docId } = await params;
  const qs = req.nextUrl.searchParams.toString();
  const path = `/api/v1/documents/${docId}/obligations${qs ? `?${qs}` : ""}`;
  const res = await backendFetch(path);
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}

/** POST /api/documents/[docId]/obligations — manual create */
export async function POST(
  req: NextRequest,
  { params }: Params
): Promise<NextResponse> {
  const { docId } = await params;
  const body: unknown = await req.json();
  const res = await backendFetch(`/api/v1/documents/${docId}/obligations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}
