import { auth } from "@clerk/nextjs/server";
import { backendUrl, loginConfigured } from "@/lib/config";
import {
  allowedRoute,
  errorResponse,
  limitedBody,
  sameOrigin,
  upstreamResponse,
} from "@/lib/gateway";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 75;

type Context = { params: Promise<{ path: string[] }> };
async function handle(request: Request, context: Context) {
  const path = (await context.params).path.join("/");
  if (!allowedRoute(path, request.method))
    return errorResponse("Route not available", 404);
  if (!sameOrigin(request))
    return errorResponse("Cross-origin mutation rejected", 403);
  if (!loginConfigured())
    return errorResponse("Workspace login is not configured yet", 503);
  const { userId, getToken } = await auth();
  if (!userId) return errorResponse("Please sign in", 401);
  try {
    const url = backendUrl(path);
    if (!url)
      return errorResponse("Workspace backend is not connected yet", 503);
    const token = await getToken({
      template: process.env.CLERK_JWT_TEMPLATE || "production-rag",
    });
    if (!token) return errorResponse("Could not verify your session", 401);
    const headers = new Headers({
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    });
    const workspace = request.headers.get("X-Workspace-ID");
    if (workspace && /^ws_[a-f0-9]{32}$/.test(workspace))
      headers.set("X-Workspace-ID", workspace);
    const response = await fetch(url, {
      method: request.method,
      headers,
      body: await limitedBody(request),
      cache: "no-store",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(70000)]),
    });
    return upstreamResponse(response);
  } catch (error) {
    if (error instanceof Error && error.message === "BODY_TOO_LARGE")
      return errorResponse("Request is too large", 413);
    return errorResponse("Workspace service temporarily unavailable", 503);
  }
}
export { handle as GET, handle as POST, handle as PUT, handle as DELETE };
