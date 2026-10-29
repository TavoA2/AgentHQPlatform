"use client";

import Link from "next/link";
import { OfficeView } from "@/components/office/office-view";
import { Card, TaskStatusBadge, formatTime } from "@/components/ui";
import { useApi } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live-events";
import type { Task } from "@/lib/types";

export default function OfficePage() {
  const tasks = useApi<Task[]>("/tasks?limit=8");
  useLiveRefresh(tasks.reload, (e) => e.type === "status_changed");

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Office</h1>

      </div>
      <OfficeView />
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
