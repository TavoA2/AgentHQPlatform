"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, api, useApi } from "@/lib/api";
import { brandName } from "@/lib/brand";
import { LiveEventsProvider, useLiveConnection, useLiveRefresh } from "@/lib/live-events";
import { SessionProvider } from "@/lib/session";
import { ALERTS_READ_EVENT, type AlertsStatus, type Approval, type Session } from "@/lib/types";

const ALERTS_POLL_MS = 15000;

const NAV = [
  { href: "/", label: "Office" },
  { href: "/chat", label: "Dixon" },
  { href: "/tasks", label: "Tasks" },
  { href: "/approvals", label: "Approvals" },
  { href: "/knowledge", label: "Brain" },
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
    <SessionProvider value={session}>
      <LiveEventsProvider>
        <Shell session={session}>{children}</Shell>
      </LiveEventsProvider>
    </SessionProvider>
  );
}

function Shell({ session, children }: { session: Session; children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const connected = useLiveConnection();
  const pending = useApi<Approval[]>("/approvals?status=pending");
  const viewer = session.user.role === "viewer";
  useLiveRefresh(pending.reload, (e) => e.type.startsWith("approval_"));
  // Alerts are delivered by the worker shortly after the events that cause them.
  const alerts = useApi<AlertsStatus>("/conversations/alerts");
  const reloadAlerts = alerts.reload;
  useEffect(() => {
    const timer = setInterval(reloadAlerts, ALERTS_POLL_MS);
    window.addEventListener(ALERTS_READ_EVENT, reloadAlerts);
    return () => {
      clearInterval(timer);
      window.removeEventListener(ALERTS_READ_EVENT, reloadAlerts);
    };
  }, [reloadAlerts]);

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
                  {item.href === "/chat" && (alerts.data?.unread ?? 0) > 0 && (
                    <span
                      className="ml-1.5 rounded-full bg-violet px-1.5 font-mono text-[10px] text-background"
                      title="Unread alerts from Dixon"
                    >
                      {alerts.data?.unread}
                    </span>
                  )}
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
          {!viewer && (
            <button onClick={logout} className="text-sm text-muted hover:text-foreground" title={session.user.email}>
              Sign out
            </button>
          )}
        </div>
        {viewer && (
          <p className="border-t border-orange/30 bg-orange/10 px-4 py-1.5 text-center text-xs text-orange">
            Public demo · read-only · sample clients and data produced by the real agent pipeline
          </p>
        )}
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
