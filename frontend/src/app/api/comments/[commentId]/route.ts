import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

interface Params {
  params: Promise<{ commentId: string }>;
}

export async function PATCH(
  req: NextRequest,
  { params }: Params
): Promise<NextResponse> {
  const { commentId } = await params;
  const body: unknown = await req.json();
  const res = await backendFetch(`/api/v1/comments/${commentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function DELETE(
  _req: NextRequest,
  { params }: Params
): Promise<NextResponse> {
  const { commentId } = await params;
  const res = await backendFetch(`/api/v1/comments/${commentId}`, {
    method: "DELETE",
  });
  // 204 No Content — return empty body
  if (res.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}
