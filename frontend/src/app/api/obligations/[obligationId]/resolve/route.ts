import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

interface Params {
  params: Promise<{ obligationId: string }>;
}

/** POST /api/obligations/[obligationId]/resolve */
export async function POST(
  _req: NextRequest,
  { params }: Params
): Promise<NextResponse> {
  const { obligationId } = await params;
  const res = await backendFetch(
    `/api/v1/obligations/${obligationId}/resolve`,
    { method: "POST", headers: { "Content-Type": "application/json" } }
  );
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}
