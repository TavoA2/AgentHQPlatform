"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, ErrorNote, TaskStatusBadge, formatTime, inputClass } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { useCanAct } from "@/lib/session";
import { useLiveRefresh } from "@/lib/live-events";
import { TASK_STATUSES, type Agent, type Project, type Task } from "@/lib/types";

export default function TasksPage() {
  const [projectId, setProjectId] = useState("");
  const [status, setStatus] = useState("");
  const [agent, setAgent] = useState("");
  const params = new URLSearchParams({ limit: "100" });
  if (projectId) params.set("project_id", projectId);
  if (status) params.set("status", status);
  if (agent) params.set("agent", agent);

  const projects = useApi<Project[]>("/projects");
  const agents = useApi<Agent[]>("/agents");
  const tasks = useApi<Task[]>(`/tasks?${params}`);
  useLiveRefresh(tasks.reload, (e) => e.type === "status_changed");
  const projectName = new Map(projects.data?.map((p) => [p.id, p.name]));
  const canAct = useCanAct();

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Tasks</h1>
      {canAct && <NewTask projects={projects.data ?? []} />}
      <Card
        title="All tasks"
        actions={
          <div className="flex flex-wrap gap-2">
            <select aria-label="Project" className={inputClass} value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">All projects</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <select aria-label="Status" className={inputClass} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {TASK_STATUSES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select aria-label="Agent" className={inputClass} value={agent} onChange={(e) => setAgent(e.target.value)}>
              <option value="">All agents</option>
              {agents.data?.map((a) => (
                <option key={a.key} value={a.key}>{a.display_name}</option>
              ))}
            </select>
          </div>
        }
      >
        <ErrorNote message={tasks.error} />
        {tasks.data?.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="pb-2 font-normal">Title</th>
                <th className="pb-2 font-normal">Project</th>
                <th className="pb-2 font-normal">Updated</th>
                <th className="pb-2 text-right font-normal">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {tasks.data.map((t) => (
                <tr key={t.id}>
                  <td className="py-2 pr-4">
                    <Link href={`/tasks/${t.id}`} className="hover:text-cyan">{t.title}</Link>
                  </td>
                  <td className="py-2 pr-4 text-muted">{projectName.get(t.project_id) ?? "—"}</td>
                  <td className="py-2 pr-4 text-muted">{formatTime(t.updated_at)}</td>
                  <td className="py-2 text-right"><TaskStatusBadge status={t.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-muted">{tasks.loading ? "Loading…" : "No tasks match."}</p>
        )}
      </Card>
    </div>
  );
}

function NewTask({ projects }: { projects: Project[] }) {
  const router = useRouter();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(undefined);
    try {
      const task = await api<Task>("/tasks", {
        method: "POST",
        body: {
          project_id: form.get("project_id"),
          title: form.get("title"),
          request: form.get("request"),
        },
      });
      if (form.get("start") === "on") await api(`/tasks/${task.id}/start`, { method: "POST" });
      router.push(`/tasks/${task.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create task");
      setBusy(false);
    }
  }

  if (!projects.length) {
    return (
      <Card title="New task">
        <p className="text-sm text-muted">
          Create a <Link href="/projects" className="text-cyan">project</Link> and authorize a repository first.
        </p>
      </Card>
    );
  }
  return (
    <Card title="New task">
      <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-[1fr_2fr]">
        <select name="project_id" required className={inputClass} aria-label="Project">
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <input name="title" required maxLength={200} placeholder="Title" className={inputClass} />
        <textarea
          name="request"
          required
          rows={3}
          placeholder="e.g. Analyze owner/repo and propose improvements to its CI/CD pipeline."
          className={`${inputClass} md:col-span-2`}
        />
        <label className="flex items-center gap-2 text-sm text-muted">
          <input type="checkbox" name="start" defaultChecked /> Start immediately
        </label>
        <div className="flex justify-end">
          <Button type="submit" disabled={busy}>{busy ? "Creating…" : "Create task"}</Button>
        </div>
        <div className="md:col-span-2"><ErrorNote message={error} /></div>
      </form>
    </Card>
  );
}
