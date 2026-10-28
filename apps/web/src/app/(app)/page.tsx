"use client";

import Link from "next/link";
import { OfficeFloor } from "@/components/office";
import { Card, ErrorNote, TaskStatusBadge, formatTime } from "@/components/ui";
import { useApi } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live-events";
import type { Agent, Task } from "@/lib/types";

export default function OfficePage() {
  const agents = useApi<Agent[]>("/agents");
  const tasks = useApi<Task[]>("/tasks?limit=8");
  useLiveRefresh(agents.reload);
  useLiveRefresh(tasks.reload, (e) => e.type === "status_changed");

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Office</h1>
        <p className="text-sm text-muted">
          Live agent status from real executions. The interactive 3D office arrives in Sprint 4.
        </p>
      </div>
      <ErrorNote message={agents.error} />
      {agents.data && <OfficeFloor agents={agents.data} />}
      <Card title="Recent tasks" actions={<Link href="/tasks" className="text-sm text-cyan">All tasks →</Link>}>
        {tasks.data?.length ? (
          <ul className="divide-y divide-border">
            {tasks.data.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-4 py-2">
                <Link href={`/tasks/${t.id}`} className="truncate hover:text-cyan">
                  {t.title}
                </Link>
                <span className="flex shrink-0 items-center gap-3 text-xs text-muted">
                  {formatTime(t.updated_at)}
                  <TaskStatusBadge status={t.status} />
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">No tasks yet.</p>
        )}
      </Card>
    </div>
  );
}
