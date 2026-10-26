export function loginConfigured() {
  return Boolean(
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY &&
    process.env.CLERK_SECRET_KEY,
  );
}
export function backendUrl(path: string): URL | null {
  const raw = process.env.RAG_API_URL;
  if (!raw) return null;
  const base = new URL(raw);
  if (base.username || base.password || base.search || base.hash)
    throw new Error("Invalid backend URL");
  if (
    base.protocol !== "https:" &&
    !(
      base.protocol === "http:" &&
      ["localhost", "127.0.0.1", "[::1]"].includes(base.hostname)
    )
  ) {
    throw new Error("Backend requires HTTPS outside localhost");
  }
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  return new URL(path, base);
}
