import { backendUrl } from "@/lib/config";
import {
  errorResponse,
  limitedBody,
  sameOrigin,
  upstreamResponse,
} from "@/lib/gateway";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 75;
export async function POST(request: Request) {
  if (!sameOrigin(request))
    return errorResponse("Cross-origin mutation rejected", 403);
  try {
    const url = backendUrl("demo/query");
    const key = process.env.DEMO_PROXY_SECRET;
    if (!url || !key)
      return errorResponse(
        "Live answers are not connected yet. Explore the guided examples below.",
        503,
      );
    const raw = await limitedBody(request, 8192);
    let body: unknown;
    try {
      body = JSON.parse(raw || "{}");
    } catch {
      return errorResponse("Invalid question", 400);
    }
    if (
      !body ||
      typeof body !== "object" ||
      !("query" in body) ||
      typeof body.query !== "string" ||
      !body.query.trim() ||
      body.query.length > 1000 ||
      Object.keys(body).some((k) => k !== "query")
    )
      return errorResponse("Enter a question up to 1,000 characters", 400);
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Demo-Key": key },
      body: JSON.stringify({ query: body.query }),
      cache: "no-store",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(70000)]),
    });
    return upstreamResponse(response);
  } catch (error) {
    if (error instanceof Error && error.message === "BODY_TOO_LARGE")
      return errorResponse("Request is too large", 413);
    return errorResponse(
      "Live answers temporarily unavailable. The guided examples are still available.",
      503,
    );
  }
}
