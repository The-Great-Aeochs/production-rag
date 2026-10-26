import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { Nav } from "@/components/nav";
import "@fontsource/manrope/400.css";
import "@fontsource/manrope/500.css";
import "@fontsource/manrope/600.css";
import "@fontsource/manrope/700.css";
import "./globals.css";
export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.SITE_URL ||
      (process.env.VERCEL_URL
        ? `https://${process.env.VERCEL_URL}`
        : "http://localhost:3000"),
  ),
  title: {
    default: "Production RAG — Document search",
    template: "%s — Production RAG",
  },
  description:
    "Search technical documentation with hybrid retrieval, source citations, and workspace permissions.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const authEnabled = Boolean(
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY &&
    process.env.CLERK_SECRET_KEY,
  );
  const content = (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <Nav authEnabled={authEnabled} />
      {children}
    </>
  );
  return (
    <html lang="en">
      <body>
        {authEnabled ? <ClerkProvider>{content}</ClerkProvider> : content}
      </body>
    </html>
  );
}
