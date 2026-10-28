"use client";

import { useState } from "react";
import { Card, TaskStatusBadge } from "@/components/ui";
import type { Changeset, QaResult, Task, TestPlan } from "@/lib/types";

/** The CIO's plan as delegated subtasks: who does what, and what each step waits for. */
export function PlanView({ subtasks }: { subtasks: Task[] }) {
  if (!subtasks.length) return null;
  return (
    <Card title="Plan and delegation">
      <ol className="flex flex-col gap-2">
        {subtasks.map((s) => (
          <li
            key={s.id}
            className="grid grid-cols-[8rem_9rem_1fr_auto] items-center gap-3 rounded-md border border-border px-3 py-2 text-sm"
          >
            <span className="font-mono text-xs text-violet">{s.assigned_agent_key}</span>
            <span className="font-mono text-xs">{s.options.step_id}</span>
            <span className="truncate text-muted" title={s.request}>
              {s.options.depends_on?.length ? `after ${s.options.depends_on.join(", ")} · ` : ""}
              {s.request}
              {s.failure_reason ? ` — ${s.failure_reason}: ${s.failure_detail ?? ""}` : ""}
            </span>
            <TaskStatusBadge status={s.status} />
          </li>
        ))}
      </ol>
    </Card>
  );
}

export function ChangesetView({ changeset }: { changeset: Changeset }) {
  const files = [...changeset.files, ...changeset.tests];
  const [open, setOpen] = useState(files[0]?.path);
  const current = files.find((f) => f.path === open);
  return (
    <Card title={`Proposed changeset · ${changeset.repository}`}>
      <p className="text-sm">{changeset.summary}</p>
      <p className="mt-1 text-sm text-muted">{changeset.rationale}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {files.map((f) => (
          <button
            key={f.path}
            onClick={() => setOpen(f.path)}
            className={`rounded border px-2 py-1 font-mono text-xs ${f.path === open ? "border-cyan text-cyan" : "border-border text-muted"}`}
          >
            {f.action === "create" ? "+ " : "~ "}
            {f.path}
          </button>
        ))}
      </div>
      {current && (
        <pre className="mt-3 max-h-96 overflow-auto rounded bg-background p-3 font-mono text-xs">
          {current.content}
        </pre>
      )}
      <p className="mt-2 text-xs text-muted">
        Proposed only: nothing is written to the repository by Agent HQ.
        {changeset.files_read.length ? ` Read for context: ${changeset.files_read.join(", ")}.` : ""}
      </p>
    </Card>
  );
}

export function QaView({ qa, plan }: { qa: QaResult; plan?: TestPlan }) {
  const run = qa.sandbox;
  const ready = qa.report.verdict === "ready";
  return (
    <Card title="QA verification">
      <p className={`font-mono text-sm ${ready ? "text-emerald-300" : "text-rose-300"}`}>
        verdict: {qa.report.verdict}
      </p>
      <p className="mt-1 text-sm">{qa.report.summary}</p>
      {qa.report.failures.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-sm text-rose-200">
          {qa.report.failures.map((f) => <li key={f}>{f}</li>)}
        </ul>
      )}
      {run && (
        <div className="mt-3">
          <p className="font-mono text-xs text-muted">
            sandbox: exit {run.exit_code ?? "—"} · {run.summary?.passed ?? 0} passed ·{" "}
            {run.summary?.failed ?? 0} failed · {run.duration_ms} ms
            {run.timed_out ? " · TIMED OUT" : ""} · no network, non-root
          </p>
          <pre className="mt-2 max-h-64 overflow-auto rounded bg-background p-3 font-mono text-xs">
            {run.output}
          </pre>
        </div>
      )}
      {plan && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-muted">Test plan ({plan.cases.length} cases)</summary>
          <ul className="mt-2 flex flex-col gap-1">
            {plan.cases.map((c) => (
              <li key={c.name}>
                <span className="font-mono text-xs">{c.name}</span> — {c.description}{" "}
                <span className="text-muted">→ {c.expected}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}
