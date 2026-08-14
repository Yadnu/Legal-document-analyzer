import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

export async function POST(req: NextRequest): Promise<NextResponse> {
  const body: unknown = await req.json();
  const res = await backendFetch("/api/v1/documents/upload-url", {
    method: "POST",
    body: JSON.stringify(body),
  });
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}
