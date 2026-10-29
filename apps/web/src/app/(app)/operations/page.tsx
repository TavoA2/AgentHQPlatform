"use client";

import Link from "next/link";
import { Card, ErrorNote, formatTime } from "@/components/ui";
import { useApi } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live-events";
import type { MetricsSummary } from "@/lib/types";

function Counts({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data);
  if (!entries.length) return <p className="text-sm text-muted">None.</p>;
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-sm">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function OperationsPage() {
  const metrics = useApi<MetricsSummary>("/metrics/summary");
  useLiveRefresh(metrics.reload, (e) => e.type === "status_changed" || e.type.startsWith("approval_"));
  const m = metrics.data;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Operations</h1>
        <p className="text-sm text-muted">
          Computed from the database{m ? ` at ${formatTime(m.generated_at)}` : ""}. Usage covers the
          last {m?.window_hours ?? 24} hours.
        </p>
      </div>
      <ErrorNote message={metrics.error} />
      {m && (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            <Card title="Tasks"><Counts data={m.tasks_by_status} /></Card>
            <Card title="Subtasks"><Counts data={m.subtasks_by_status} /></Card>
            <Card title="Job queue"><Counts data={m.jobs_by_status} /></Card>
            <Card title="Approvals">
              <p className="font-mono text-sm">{m.approvals_pending} pending</p>
              <p className="mt-1 font-mono text-xs text-muted">
                median decision:{" "}
                {m.approval_median_seconds == null ? "—" : `${Math.round(m.approval_median_seconds)} s`}
              </p>
            </Card>
          </div>
          <Card title="Agent usage">
            <table className="w-full font-mono text-xs">
              <thead className="text-left text-muted">
                <tr>
                  <th className="pb-2 font-normal">Agent</th>
                  <th className="pb-2 font-normal">Executions</th>
                  <th className="pb-2 font-normal">Running</th>
                  <th className="pb-2 font-normal">Failed</th>
                  <th className="pb-2 font-normal">Tokens in / out</th>
                  <th className="pb-2 font-normal">Est. cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {m.agents.map((a) => (
                  <tr key={a.key}>
                    <td className="py-2">{a.key}</td>
                    <td>{a.executions}</td>
                    <td>{a.running}</td>
                    <td className={a.failed ? "text-rose-300" : ""}>{a.failed}</td>
                    <td>{a.tokens_in} / {a.tokens_out}</td>
                    <td>{a.cost_usd ? `$${Number(a.cost_usd).toFixed(4)}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <Card title="Recent failed jobs">
            {m.recent_failed_jobs.length ? (
              <ul className="flex flex-col gap-2 text-sm">
                {m.recent_failed_jobs.map((j) => (
                  <li key={j.id} className="font-mono text-xs">
                    #{j.id} {j.kind} ·{" "}
                    {j.task_id ? (
                      <Link href={`/tasks/${j.task_id}`} className="text-cyan">task</Link>
                    ) : (
                      "chat"
                    )}{" "}
                    · {j.attempts}{" "}
                    attempts · {formatTime(j.updated_at)}
                    <span className="block text-muted">{j.last_error}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">None.</p>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
