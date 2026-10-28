"use client";

import Link from "next/link";
import type { Agent, AgentStatus } from "@/lib/types";
import { AgentStatusBadge } from "@/components/ui";

// Sprint 1 placeholder for the 3D office (Sprint 4): a 2D floor plan whose desks reflect
// only real agent status from the API. It doubles as the accessible / reduced-motion view.

const DEPARTMENTS: { key: string; label: string; accent: string }[] = [
  { key: "executive", label: "Executive", accent: "from-violet/30" },
  { key: "engineering", label: "Engineering", accent: "from-cyan/25" },
];

const STATUS_HINT: Record<AgentStatus, string> = {
  IDLE: "Standing by",
  RUNNING: "Working at desk",
  WAITING_APPROVAL: "Waiting for your approval",
  FAILED: "Last run failed",
};

function Avatar({ status }: { status: AgentStatus }) {
  const color = {
    IDLE: "bg-muted/60",
    RUNNING: "bg-cyan",
    WAITING_APPROVAL: "bg-orange",
    FAILED: "bg-rose-400",
  }[status];
  return (
    <span className="relative flex h-10 w-10 items-center justify-center" aria-hidden>
      {status === "RUNNING" && (
        <span className="absolute inset-0 rounded-full bg-cyan/30 motion-safe:animate-ping" />
      )}
      <span className={`relative h-6 w-6 rounded-full ${color}`} />
      {status === "WAITING_APPROVAL" && (
        <span className="absolute -right-1 -top-1 rounded-full bg-orange px-1 font-mono text-[10px] font-bold text-background">
          !
        </span>
      )}
      {status === "FAILED" && (
        <span className="absolute -right-1 -top-1 rounded-full bg-rose-400 px-1 font-mono text-[10px] font-bold text-background">
          ×
        </span>
      )}
    </span>
  );
}

function Desk({ agent }: { agent: Agent }) {
  const exec = agent.last_execution;
  return (
    <article className="rounded-lg border border-border bg-background/60 p-4">
      <div className="flex items-center gap-3">
        <Avatar status={agent.status} />
        <div className="min-w-0 flex-1">
          <h3 className="font-medium">{agent.display_name}</h3>
          <p className="text-xs text-muted">{STATUS_HINT[agent.status]}</p>
        </div>
        <AgentStatusBadge status={agent.status} />
      </div>
      <p className="mt-3 text-sm text-muted">{agent.description}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-xs text-muted">
        <dt>model profile</dt>
        <dd className="text-foreground">{agent.model_profile}</dd>
        <dt>last model</dt>
        <dd className="truncate text-foreground">{exec?.model_name ?? "—"}</dd>
        <dt>tokens</dt>
        <dd className="text-foreground">{exec ? exec.tokens_in + exec.tokens_out : 0}</dd>
      </dl>
      {agent.current_task_id && (
        <Link href={`/tasks/${agent.current_task_id}`} className="mt-3 inline-block text-sm text-cyan hover:underline">
          Open current task →
        </Link>
      )}
    </article>
  );
}

export function OfficeFloor({ agents }: { agents: Agent[] }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {DEPARTMENTS.map((dept) => {
        const members = agents.filter((a) => a.department === dept.key);
        return (
          <section
            key={dept.key}
            aria-label={`${dept.label} department`}
            className={`rounded-xl border border-border bg-gradient-to-br ${dept.accent} to-transparent p-4`}
          >
            <h2 className="mb-3 font-mono text-xs uppercase tracking-widest text-muted">{dept.label}</h2>
            <div className="grid gap-3">
              {members.length ? members.map((a) => <Desk key={a.key} agent={a} />) : (
                <p className="text-sm text-muted">No agents yet.</p>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
