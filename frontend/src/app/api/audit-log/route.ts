import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

export async function GET(req: NextRequest): Promise<NextResponse> {
  // Forward query string (action, limit, offset, since) to FastAPI unchanged.
  const qs = req.nextUrl.searchParams.toString();
  const path = `/api/v1/audit-log${qs ? `?${qs}` : ""}`;
  const res = await backendFetch(path);
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}
