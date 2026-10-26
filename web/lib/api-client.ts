/** Browser requests use the same-origin gateway; authorization stays server-side. */
export async function responseError(
  response: Response,
  fallback = "Request failed. Please try again.",
) {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return new Error(body.detail);
  } catch {
    /* An upstream outage may return a non-JSON response. */
  }
  return new Error(fallback);
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api/${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });
  if (!response.ok) throw await responseError(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
