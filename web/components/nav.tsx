"use client";
import Link from "next/link";
import { useAuth, UserButton } from "@clerk/nextjs";
import { Menu, X } from "lucide-react";
import { useRef, useState } from "react";
import { repository } from "@/lib/samples";
function Account() {
  const { isLoaded, isSignedIn } = useAuth();
  return isLoaded && isSignedIn ? (
    <>
      <Link href="/workspace" className="nav-login">
        Workspace
      </Link>
      <UserButton />
    </>
  ) : (
    <Link href="/sign-in" className="nav-login">
      Sign in
    </Link>
  );
}
function Mark() {
  return (
    <span className="wordmark">
      <span className="brand-mark" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      production<span className="wordmark-dot">.</span>rag
    </span>
  );
}
export function Nav({ authEnabled = false }: { authEnabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  return (
    <header
      className="site-header"
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          setOpen(false);
          toggle.current?.focus();
        }
      }}
    >
      <div className="nav-shell">
        <Link href="/" aria-label="Production RAG home">
          <Mark />
        </Link>
        <button
          type="button"
          className="mobile-toggle"
          ref={toggle}
          aria-expanded={open}
          aria-label="Toggle navigation"
          aria-controls="main-navigation"
          onClick={() => setOpen(!open)}
        >
          {open ? <X /> : <Menu />}
        </button>
        <nav
          className={open ? "main-nav is-open" : "main-nav"}
          aria-label="Main navigation"
          id="main-navigation"
        >
          <Link href="/#demo" onClick={() => setOpen(false)}>
            Demo
          </Link>
          <Link href="/#architecture" onClick={() => setOpen(false)}>
            How it works
          </Link>
          <Link href="/#access" onClick={() => setOpen(false)}>
            Permissions
          </Link>
          <Link href="/docs" onClick={() => setOpen(false)}>
            Docs
          </Link>
        </nav>
        <div className="nav-actions">
          <a href={repository} className="nav-source">
            GitHub
          </a>
          {authEnabled ? (
            <Account />
          ) : (
            <Link href="/workspace" className="nav-login">
              Workspace
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
