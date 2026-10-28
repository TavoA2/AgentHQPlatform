import { Suspense } from "react";
import { brandName } from "@/lib/brand";

type HealthStatus = {
  status: "ok" | "unavailable";
  version: string;
  checks: Record<string, "ok" | "fail">;
};

async function fetchReadiness(): Promise<HealthStatus | null> {
  const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${apiUrl}/health/ready`, { cache: "no-store" });
    return (await res.json()) as HealthStatus;
  } catch {
    return null;
  }
}

async function ApiStatus() {
  const health = await fetchReadiness();
  if (!health) {
    return <StatusRow label="API" ok={false} detail="unreachable" />;
  }
  return (
    <>
      <StatusRow label="API" ok detail={`v${health.version}`} />
      {Object.entries(health.checks).map(([name, result]) => (
        <StatusRow key={name} label={name} ok={result === "ok"} detail={result} />
      ))}
    </>
  );
}

function StatusRow({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <li className="flex items-center justify-between py-2">
      <span className="capitalize">{label}</span>
      <span className={`font-mono text-sm ${ok ? "text-cyan" : "text-orange"}`}>
        {ok ? "●" : "○"} {detail}
      </span>
    </li>
  );
}

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center gap-8 px-6 py-16">
      <header>
        <p className="font-mono text-sm uppercase tracking-widest text-violet">{brandName}</p>
        <h1 className="mt-2 text-3xl font-semibold">Agent HQ</h1>
        <p className="mt-2 text-muted">
          Sprint 0 foundation. The dashboard and agent office arrive in Sprint 1.
        </p>
      </header>
      <section className="rounded-lg border border-border bg-surface px-5 py-3">
        <h2 className="py-2 text-sm font-medium text-muted">System status</h2>
        <ul className="divide-y divide-border">
          <Suspense fallback={<li className="py-2 text-muted">Checking…</li>}>
            <ApiStatus />
          </Suspense>
        </ul>
      </section>
    </main>
  );
}
