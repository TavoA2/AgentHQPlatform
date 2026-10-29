"use client";

import Link from "next/link";
import { AgentStatusBadge, TaskStatusBadge, formatTime } from "@/components/ui";
import { useApi } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live-events";
import type { AgentDetail } from "@/lib/types";

/** Detail for the selected agent. Shared by the 3D and 2D views; fully keyboard usable. */
export function AgentPanel({ agentKey, onClose }: { agentKey: string; onClose: () => void }) {
  const detail = useApi<AgentDetail>(`/agents/${agentKey}`);
  useLiveRefresh(detail.reload, (e) => e.agent_key === agentKey || e.type.startsWith("approval_"));
  const a = detail.data;

  return (
    <aside
      aria-label="Agent details"
      className="flex max-h-[70vh] flex-col overflow-hidden rounded-lg border border-border bg-surface"
    >
      <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h2 className="font-medium">{a?.display_name ?? agentKey}</h2>
          {a && <p className="text-xs text-muted">{a.description}</p>}
        </div>
        <button onClick={onClose} className="text-sm text-muted hover:text-foreground" aria-label="Close details">
          ✕
        </button>
      </header>
      {!a ? (
        <p className="p-4 text-sm text-muted">Loading…</p>
      ) : (
        <div className="flex flex-col gap-4 overflow-y-auto p-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <AgentStatusBadge status={a.status} />
            <span className="font-mono text-xs text-muted">
              {a.department} · profile {a.model_profile}
            </span>
          </div>
          {a.current_task_id && (
            <Link href={`/tasks/${a.current_task_id}`} className="text-cyan hover:underline">
              Open current task →
            </Link>
          )}
          {a.pending_approvals > 0 && (
            <Link href="/approvals" className="rounded-md border border-orange/40 px-3 py-2 text-orange">
              {a.pending_approvals} approval{a.pending_approvals > 1 ? "s" : ""} waiting for you →
            </Link>
          )}
          <section>
            <h3 className="mb-1 text-xs uppercase tracking-wide text-muted">Permitted tools</h3>
            <p className="font-mono text-xs">{a.allowed_tools.join(", ")}</p>
          </section>
          <section>
            <h3 className="mb-2 text-xs uppercase tracking-wide text-muted">Recent activity</h3>
            {a.recent_activity.length ? (
              <ol className="flex flex-col gap-2">
                {a.recent_activity.map((r) => (
                  <li key={r.execution.id} className="rounded-md border border-border p-2">
                    <div className="flex items-center justify-between gap-2">
                      <Link
                        href={`/tasks/${r.parent_task_id ?? r.task_id}`}
                        className="truncate hover:text-cyan"
                        title={r.task_title}
                      >
                        {r.task_title}
                      </Link>
                      <TaskStatusBadge status={r.task_status} />
                    </div>
                    <p className="mt-1 font-mono text-[11px] text-muted">
                      {r.execution.status} · attempt {r.execution.attempt} · {formatTime(r.execution.started_at)}
                      {r.execution.model_name ? ` · ${r.execution.model_name}` : ""} ·{" "}
                      {r.execution.tokens_in + r.execution.tokens_out} tokens
                    </p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-muted">No executions yet.</p>
            )}
          </section>
        </div>
      )}
    </aside>
  );
}
