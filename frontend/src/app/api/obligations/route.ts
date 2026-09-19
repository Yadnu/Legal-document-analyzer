import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

/** GET /api/obligations — tenant-wide obligation list */
export async function GET(req: NextRequest): Promise<NextResponse> {
  const qs = req.nextUrl.searchParams.toString();
  const path = `/api/v1/obligations${qs ? `?${qs}` : ""}`;
  const res = await backendFetch(path);
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}
