import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/backend";

interface Params {
  params: Promise<{ inviteId: string }>;
}

export async function DELETE(
  _req: NextRequest,
  { params }: Params
): Promise<NextResponse> {
  const { inviteId } = await params;
  const res = await backendFetch(`/api/v1/workspace/invites/${inviteId}`, {
    method: "DELETE",
  });
  if (res.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  const data: unknown = await res.json();
  return NextResponse.json(data, { status: res.status });
}
