"use client";
import Link from "next/link";
import { useAuth, UserButton } from "@clerk/nextjs";
import { ArrowUpRight, GitBranch, Menu, X } from "lucide-react";
import { useState } from "react";
import { repository } from "@/lib/samples";
function Account() {
  const { isLoaded, isSignedIn } = useAuth();
  return isLoaded && isSignedIn ? (
    <>
      <Link href="/workspace" className="nav-login">
        Workspace <ArrowUpRight size={14} />
      </Link>
      <UserButton />
    </>
  ) : (
    <Link href="/sign-in" className="nav-login">
      Sign in <ArrowUpRight size={14} />
    </Link>
  );
}
export function Mark() {
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
  return (
    <header className="site-header">
      <div className="nav-shell">
        <Link href="/" aria-label="Production RAG home">
          <Mark />
        </Link>
        <button
          type="button"
          className="mobile-toggle"
          aria-expanded={open}
          aria-label="Toggle navigation"
          onClick={() => setOpen(!open)}
        >
          {open ? <X /> : <Menu />}
        </button>
        <nav
          className={open ? "main-nav is-open" : "main-nav"}
          aria-label="Main navigation"
        >
          <Link href="/#demo" onClick={() => setOpen(false)}>
            Playground
          </Link>
          <Link href="/#architecture" onClick={() => setOpen(false)}>
            Architecture
          </Link>
          <Link href="/#access" onClick={() => setOpen(false)}>
            Access control
          </Link>
          <Link href="/docs" onClick={() => setOpen(false)}>
            Docs
          </Link>
        </nav>
        <div className="nav-actions">
          <a
            href={repository}
            target="_blank"
            rel="noreferrer"
            aria-label="View source on GitHub"
            className="github-icon"
          >
            <GitBranch size={19} />
          </a>
          {authEnabled ? (
            <Account />
          ) : (
            <Link href="/workspace" className="nav-login">
              Workspace <ArrowUpRight size={14} />
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
