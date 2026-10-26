import Link from "next/link";
import { auth } from "@clerk/nextjs/server";
import { ArrowRight } from "lucide-react";
import { WorkspaceApp } from "@/components/workspace";
import { loginConfigured } from "@/lib/config";
export const dynamic = "force-dynamic";
export const metadata = { title: "Your workspace" };
export default async function Workspace() {
  if (!loginConfigured())
    return (
      <main id="main" className="page-shell">
        <h1>Workspaces</h1>
        <div className="notice-panel">
          <h2>Workspace login is unavailable</h2>
          <p>
            Login has not been configured for this deployment. Browse the public
            demo to see example answers and sources.
          </p>
          <Link href="/#demo" className="button primary">
            View the demo <ArrowRight size={15} aria-hidden="true" />
          </Link>
        </div>
      </main>
    );
  const { userId, redirectToSignIn } = await auth();
  if (!userId) return redirectToSignIn({ returnBackUrl: "/workspace" });
  return (
    <main id="main">
      <WorkspaceApp />
    </main>
  );
}
