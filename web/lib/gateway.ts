const workspace = "ws_[a-f0-9]{32}";
const user = "usr_[a-f0-9]{64}";
const policies: [RegExp, string[]][] = [
  [/^workspaces$/, ["GET", "POST"]],
  [new RegExp(`^workspaces/${workspace}/members$`), ["GET"]],
  [new RegExp(`^workspaces/${workspace}/members/${user}$`), ["PUT", "DELETE"]],
  [new RegExp(`^workspaces/${workspace}/documents$`), ["GET"]],
  [new RegExp(`^workspaces/${workspace}/ingest$`), ["POST"]],
  [new RegExp(`^workspaces/${workspace}/jobs/[a-f0-9]{32}$`), ["GET"]],
  [new RegExp(`^workspaces/${workspace}/audit$`), ["GET"]],
  [/^session$/, ["POST"]],
  [/^query\/stream$/, ["POST"]],
];
export function allowedRoute(path: string, method: string) {
  return policies.some(
    ([pattern, methods]) => pattern.test(path) && methods.includes(method),
  );
}
export function sameOrigin(request: Request) {
  if (["GET", "HEAD"].includes(request.method)) return true;
  const origin = request.headers.get("origin");
  const url = new URL(request.url);
  // Next.js may normalize the internal URL to localhost; the browser's Host
  // remains the external authority. Never trust a forwarded-host override.
  const host = request.headers.get("host");
  return origin === (host ? `${url.protocol}//${host}` : url.origin);
}
export async function limitedBody(
  request: Request,
  max = 65536,
): Promise<string | undefined> {
  if (["GET", "HEAD"].includes(request.method) || !request.body)
    return undefined;
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > max) {
        await reader.cancel();
        throw new Error("BODY_TOO_LARGE");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}
export function upstreamResponse(response: Response) {
  const headers = new Headers({ "Cache-Control": "no-store" });
  for (const name of ["content-type", "retry-after", "x-request-id"]) {
    const value = response.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (response.headers.get("content-type")?.includes("text/event-stream"))
    headers.set("X-Accel-Buffering", "no");
  return new Response(response.body, { status: response.status, headers });
}
export function errorResponse(detail: string, status: number) {
  return Response.json(
    { detail },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}
