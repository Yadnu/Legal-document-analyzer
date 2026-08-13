import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

interface Params {
  params: Promise<{ docId: string }>;
}

export async function POST(_req: NextRequest, { params }: Params): Promise<NextResponse> {
  const { docId } = await params;
  const res = await backendFetch(`/api/v1/documents/${docId}/confirm`, {
    method: "POST",
  });
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}
