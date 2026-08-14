/**
 * Server-side helper for calling the FastAPI backend from Next.js route handlers.
 * Attaches the Clerk session token as a Bearer Authorization header.
 */
import { auth } from "@clerk/nextjs/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function backendFetch(
  path: string,
  init?: RequestInit
): Promise<Response> {
  const { getToken } = await auth();
  const token = await getToken();

  return fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
}
