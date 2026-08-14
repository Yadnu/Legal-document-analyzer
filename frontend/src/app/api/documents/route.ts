import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

export async function GET(): Promise<NextResponse> {
  const res = await backendFetch("/api/v1/documents");
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}
