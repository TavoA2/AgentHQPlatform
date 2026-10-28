"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, api, useApi } from "@/lib/api";
import { brandName } from "@/lib/brand";
import { LiveEventsProvider, useLiveConnection, useLiveRefresh } from "@/lib/live-events";
import type { Approval, Session } from "@/lib/types";

const NAV = [
  { href: "/", label: "Office" },
  { href: "/tasks", label: "Tasks" },
  { href: "/approvals", label: "Approvals" },
  { href: "/projects", label: "Projects" },
  { href: "/operations", label: "Operations" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    api<Session>("/auth/me")
      .then(setSession)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login");
      });
  }, [router]);

  if (!session) {
    return <div className="flex flex-1 items-center justify-center text-muted">Loading…</div>;
  }
  return (
    <LiveEventsProvider>
      <Shell session={session}>{children}</Shell>
    </LiveEventsProvider>
  );
}

function Shell({ session, children }: { session: Session; children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const connected = useLiveConnection();
  const pending = useApi<Approval[]>("/approvals?status=pending");
  useLiveRefresh(pending.reload, (e) => e.type.startsWith("approval_"));

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login");
  }

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="sticky top-0 z-10 border-b border-border bg-background/90 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-6 px-4 py-3">
          <Link href="/" className="flex items-baseline gap-2">
            <span className="font-mono text-xs uppercase tracking-widest text-violet">{brandName}</span>
            <span className="font-semibold">Agent HQ</span>
          </Link>
          <nav className="flex flex-1 gap-1 overflow-x-auto">
            {NAV.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-md px-3 py-1.5 text-sm ${active ? "bg-surface text-foreground" : "text-muted hover:text-foreground"}`}
                >
                  {item.label}
                  {item.href === "/approvals" && (pending.data?.length ?? 0) > 0 && (
                    <span className="ml-1.5 rounded-full bg-orange px-1.5 font-mono text-[10px] text-background">
                      {pending.data?.length}
                    </span>
                  )}
                </Link>
              );
            })}
          </nav>
          <span
            className={`hidden font-mono text-xs sm:inline ${connected ? "text-cyan" : "text-orange"}`}
            title="Real-time event stream"
          >
            {connected ? "● live" : "○ reconnecting"}
          </span>
          <button onClick={logout} className="text-sm text-muted hover:text-foreground" title={session.user.email}>
            Sign out
          </button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
