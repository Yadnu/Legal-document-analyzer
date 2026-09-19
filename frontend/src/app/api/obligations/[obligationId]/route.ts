import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

interface Params {
  params: Promise<{ obligationId: string }>;
}

/** PATCH /api/obligations/[obligationId] */
export async function PATCH(
  req: NextRequest,
  { params }: Params
): Promise<NextResponse> {
  const { obligationId } = await params;
  const body: unknown = await req.json();
  const res = await backendFetch(`/api/v1/obligations/${obligationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}

/** POST /api/obligations/[obligationId]/resolve is handled by a sub-route. */
