"use client";

import type { Agent, AgentStatus } from "@/lib/types";
import { AgentStatusBadge } from "@/components/ui";
import { departmentsFor } from "./model";

// Accessible 2D office: shown when WebGL is unavailable or reduced motion is preferred.
// Same data and selection as the 3D view; every desk is a keyboard-focusable button.

const STATUS_HINT: Record<AgentStatus, string> = {
  IDLE: "Standing by",
  RUNNING: "Working at desk",
  WAITING_APPROVAL: "Waiting for your approval",
  FAILED: "Last run failed",
};

function Avatar({ status, completed }: { status: AgentStatus; completed: boolean }) {
  const color = {
    IDLE: completed ? "bg-emerald-400" : "bg-muted/60",
    RUNNING: "bg-cyan",
    WAITING_APPROVAL: "bg-orange",
    FAILED: "bg-rose-400",
  }[status];
  return (
    <span className="relative flex h-10 w-10 items-center justify-center" aria-hidden>
      {status === "RUNNING" && <span className="absolute inset-0 rounded-full bg-cyan/30 motion-safe:animate-ping" />}
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
      {completed && status === "IDLE" && (
        <span className="absolute -right-1 -top-1 rounded-full bg-emerald-400 px-1 font-mono text-[10px] font-bold text-background">
          ✓
        </span>
      )}
    </span>
  );
}

export function OfficeFloor({
  agents,
  selected,
  onSelect,
  completed,
}: {
  agents: Agent[];
  selected: string | null;
  onSelect: (key: string) => void;
  completed: ReadonlySet<string>;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {departmentsFor(agents).map((dept) => {
        const members = agents.filter((a) => a.department === dept.key);
        return (
          <section
            key={dept.key}
            aria-label={`${dept.label} department`}
            className="rounded-xl border border-border bg-surface/60 p-4"
            style={{ borderTopColor: dept.accent, borderTopWidth: 3 }}
          >
            <h2 className="mb-3 font-mono text-xs uppercase tracking-widest" style={{ color: dept.accent }}>
              {dept.label}
            </h2>
            <div className="grid gap-3">
              {members.length ? (
                members.map((agent) => {
                  const done = completed.has(agent.key);
                  return (
                    <button
                      key={agent.key}
                      onClick={() => onSelect(agent.key)}
                      aria-pressed={selected === agent.key}
                      className={`rounded-lg border bg-background/60 p-3 text-left transition-colors ${selected === agent.key ? "border-cyan" : "border-border hover:border-cyan/50"}`}
                    >
                      <div className="flex items-center gap-3">
                        <Avatar status={agent.status} completed={done} />
                        <div className="min-w-0 flex-1">
                          <h3 className="font-medium">{agent.display_name}</h3>
                          <p className="text-xs text-muted">{done ? "Just finished" : STATUS_HINT[agent.status]}</p>
                        </div>
                        <AgentStatusBadge status={agent.status} />
                      </div>
                    </button>
                  );
                })
              ) : (
                <p className="text-sm text-muted">No agents yet.</p>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
