"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ApprovalCard } from "@/components/approval-card";
import { Button, Card, ErrorNote, TaskStatusBadge, formatTime } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { useLiveRefresh, useTaskEventFeed } from "@/lib/live-events";
import type { TaskDetail, TaskEvent, TaskStatus } from "@/lib/types";

const STARTABLE: TaskStatus[] = ["DRAFT", "PLANNED", "FAILED"];
const CANCELLABLE: TaskStatus[] = ["DRAFT", "PLANNED", "QUEUED", "RUNNING", "WAITING_APPROVAL"];
const SEVERITY_TONE = {
  critical: "text-rose-300",
  high: "text-rose-300",
  medium: "text-orange",
  low: "text-muted",
} as const;

export default function TaskPage() {
  const { id } = useParams<{ id: string }>();
  const task = useApi<TaskDetail>(`/tasks/${id}`);
  const history = useApi<TaskEvent[]>(`/tasks/${id}/events`);
  const [live, setLive] = useState<TaskEvent[]>([]);
  const [error, setError] = useState<string>();

  useLiveRefresh(task.reload, (e) => e.task_id === id);
  useTaskEventFeed(id, (event) => setLive((prev) => [...prev, event]));

  const lastHistoryId = history.data?.at(-1)?.id ?? 0;
  const events = [...(history.data ?? []), ...live.filter((e) => e.id > lastHistoryId)];

  async function act(action: "start" | "cancel") {
    setError(undefined);
    try {
      await api(`/tasks/${id}/${action}`, { method: "POST" });
      task.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not ${action}`);
    }
  }

  if (task.error) return <ErrorNote message={task.error} />;
  if (!task.data) return <p className="text-muted">Loading…</p>;
  const t = task.data;
  const rec = t.result?.recommendation;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{t.title}</h1>
          <p className="mt-1 max-w-3xl whitespace-pre-wrap text-sm text-muted">{t.request}</p>
        </div>
        <div className="flex items-center gap-3">
          <TaskStatusBadge status={t.status} />
          {STARTABLE.includes(t.status) && (
            <Button onClick={() => act("start")}>{t.status === "FAILED" ? "Retry" : "Start"}</Button>
          )}
          {CANCELLABLE.includes(t.status) && (
            <Button variant="danger" onClick={() => act("cancel")}>Cancel</Button>
          )}
        </div>
      </header>
      <ErrorNote message={error} />
      {t.status === "FAILED" && (
        <ErrorNote message={`Failed: ${t.failure_reason}${t.failure_detail ? ` — ${t.failure_detail}` : ""}`} />
      )}

      {t.approvals.filter((a) => a.status === "pending").map((a) => (
        <ApprovalCard key={a.id} approval={a} onDecided={task.reload} />
      ))}

      {t.result?.summary && (
        <Card title="Outcome">
          <p className="text-sm">{t.result.summary.outcome}</p>
          {t.result.summary.risks.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-sm text-muted">
              {t.result.summary.risks.map((r) => <li key={r}>{r}</li>)}
            </ul>
          )}
          {t.result.publication && (
            <p className="mt-2 font-mono text-xs text-muted">
              published to {t.result.publication.location}
              {t.result.publication.mock ? " (mock adapter)" : ""}
            </p>
          )}
        </Card>
      )}

      {rec && (
        <Card title={`CI/CD review · ${rec.repository}`}>
          <p className="mb-3 font-mono text-xs text-muted">
            Evidence: {rec.files_inspected.map((f) => f.path).join(", ")}
            {t.result?.verification?.passed ? " · verified" : ""}
          </p>
          <h3 className="mb-2 text-sm font-medium">Findings ({rec.findings.length})</h3>
          <ul className="mb-4 flex flex-col gap-2">
            {rec.findings.map((f, i) => (
              <li key={i} className="text-sm">
                <span className={`font-mono text-xs uppercase ${SEVERITY_TONE[f.severity]}`}>{f.severity}</span>{" "}
                <span className="font-mono text-xs text-muted">{f.file}</span> — {f.description}
              </li>
            ))}
          </ul>
          <h3 className="mb-2 text-sm font-medium">Recommendations ({rec.recommendations.length})</h3>
          <div className="flex flex-col gap-3">
            {rec.recommendations.map((r, i) => (
              <div key={i} className="rounded-md border border-border p-3">
                <p className="text-sm font-medium">{r.title}</p>
                <p className="text-sm text-muted">{r.rationale}</p>
                <pre className="mt-2 overflow-x-auto rounded bg-background p-2 font-mono text-xs">{r.proposed_change}</pre>
                <p className="mt-1 font-mono text-xs text-muted">effort {r.effort} · risk {r.risk}</p>
              </div>
            ))}
          </div>
          {rec.limitations.length > 0 && (
            <p className="mt-3 text-xs text-muted">Limitations: {rec.limitations.join(" ")}</p>
          )}
        </Card>
      )}

      <Card title="Executions">
        {t.executions.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="pb-2 font-normal">Agent</th>
                <th className="pb-2 font-normal">Run / attempt</th>
                <th className="pb-2 font-normal">Status</th>
                <th className="pb-2 font-normal">Model</th>
                <th className="pb-2 font-normal">Tokens in/out</th>
                <th className="pb-2 font-normal">Est. cost</th>
                <th className="pb-2 font-normal">Started</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border font-mono text-xs">
              {t.executions.map((e) => (
                <tr key={e.id}>
                  <td className="py-2">{e.agent_key}</td>
                  <td>{e.run_number} / {e.attempt}</td>
                  <td>{e.status}{e.error ? ` (${String(e.error.reason ?? "")})` : ""}</td>
                  <td>{e.model_name ?? "—"}</td>
                  <td>{e.tokens_in} / {e.tokens_out}</td>
                  <td>{e.cost_usd ? `$${Number(e.cost_usd).toFixed(4)}` : "—"}</td>
                  <td>{formatTime(e.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-muted">Not started.</p>
        )}
      </Card>

      <EventLog events={events} />
    </div>
  );
}

function EventLog({ events }: { events: TaskEvent[] }) {
  const [open, setOpen] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  return (
    <Card
      title={`Event log (${events.length})`}
      actions={<button className="text-sm text-muted" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"}</button>}
    >
      {open && (
        <ol className="flex max-h-96 flex-col gap-1 overflow-y-auto font-mono text-xs">
          {events.map((e) => (
            <li key={e.id} className="grid grid-cols-[4rem_7rem_8rem_1fr] gap-2">
              <span className="text-muted">#{e.id}</span>
              <span className="text-muted" title={e.created_at}>
                {Math.max(0, Math.round((now - new Date(e.created_at).getTime()) / 1000))}s ago
              </span>
              <span className="text-violet">{e.agent_key ?? "system"}</span>
              <span className="truncate">
                {e.type} {summarize(e)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function summarize(e: TaskEvent): string {
  const p = e.payload;
  switch (e.type) {
    case "status_changed":
      return `${p.from} → ${p.to}${p.reason ? ` (${p.reason})` : ""}`;
    case "tool_called":
      return `${p.tool} ${p.denied ? "DENIED" : p.ok ? "ok" : "error"}${p.error ? `: ${p.error}` : ""}`;
    case "model_called":
      return `${p.model} ${p.tokens_in}/${p.tokens_out} tokens`;
    case "step":
      return String(p.node ?? "");
    default:
      return "";
  }
}
