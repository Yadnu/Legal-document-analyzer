import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

interface Params {
  params: Promise<{ userId: string }>;
}

export async function PATCH(
  req: NextRequest,
  { params }: Params
): Promise<NextResponse> {
  const { userId } = await params;
  const body: unknown = await req.json();
  const res = await backendFetch(
    `/api/v1/workspace/members/${encodeURIComponent(userId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(body),
    }
  );
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function DELETE(
  _req: NextRequest,
  { params }: Params
): Promise<NextResponse> {
  const { userId } = await params;
  const res = await backendFetch(
    `/api/v1/workspace/members/${encodeURIComponent(userId)}`,
    { method: "DELETE" }
  );
  if (res.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}
