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
        <p className="eyebrow">YOUR OWN CONTEXT</p>
        <h1>
          A place for your
          <br />
          <em>team’s knowledge.</em>
        </h1>
        <div className="notice-panel">
          <h2>Workspace sign-in is coming online.</h2>
          <p>
            Login isn’t configured on this deployment yet. You can still explore
            the public playground and see how the system works.
          </p>
          <Link href="/#demo" className="button primary">
            Explore the playground <ArrowRight size={15} />
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
