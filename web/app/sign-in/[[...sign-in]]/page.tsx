import { SignIn } from "@clerk/nextjs";
import Link from "next/link";
import { loginConfigured } from "@/lib/config";
export const dynamic = "force-dynamic";
export default function SignInPage() {
  return (
    <main id="main" className="sign-in-shell">
      {loginConfigured() ? (
        <SignIn />
      ) : (
        <div className="notice-panel">
          <h2>Sign-in is unavailable</h2>
          <p>
            Login has not been configured for this deployment. The public demo
            is available.
          </p>
          <Link className="button secondary" href="/#demo">
            View the demo
          </Link>
        </div>
      )}
    </main>
  );
}
