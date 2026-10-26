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
          <h2>Sign-in isn’t available yet.</h2>
          <p>
            The public playground is open while workspace login is being
            configured.
          </p>
          <Link className="button secondary" href="/#demo">
            Explore the playground
          </Link>
        </div>
      )}
    </main>
  );
}
