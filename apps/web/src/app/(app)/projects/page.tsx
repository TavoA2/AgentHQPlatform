"use client";

import { useState } from "react";
import { Button, Card, ErrorNote, inputClass } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { useCanAct } from "@/lib/session";
import type { Integration, Project, ProjectDetail } from "@/lib/types";

export default function ProjectsPage() {
  const projects = useApi<Project[]>("/projects");
  const canAct = useCanAct();
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Projects</h1>
      {canAct && <NewProject onCreated={projects.reload} />}
      <ErrorNote message={projects.error} />
      {projects.data?.map((p) => <ProjectRow key={p.id} projectId={p.id} />)}
    </div>
  );
}

function NewProject({ onCreated }: { onCreated: () => void }) {
  const [error, setError] = useState<string>();

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formEl = event.currentTarget;
    const form = new FormData(formEl);
    setError(undefined);
    try {
      await api("/projects", {
        method: "POST",
        body: {
          key: form.get("key"),
          name: form.get("name"),
          client_name: form.get("client_name") || null,
        },
      });
      formEl.reset();
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create project");
    }
  }

  return (
    <Card title="New project">
      <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-4">
        <input name="key" required pattern="[a-z0-9][a-z0-9-]{1,62}" placeholder="key (e.g. agent-hq)" className={inputClass} />
        <input name="name" required placeholder="Name" className={inputClass} />
        <input name="client_name" placeholder="Client (optional)" className={inputClass} />
        <Button type="submit">Create</Button>
        <div className="md:col-span-4"><ErrorNote message={error} /></div>
      </form>
    </Card>
  );
}

function ProjectRow({ projectId }: { projectId: string }) {
  const project = useApi<ProjectDetail>(`/projects/${projectId}`);
  const github: Integration | undefined = project.data?.integrations.find((i) => i.provider === "github");
  const [repos, setRepos] = useState<string>();
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState(false);
  const [prs, setPrs] = useState<boolean>();
  const canAct = useCanAct();
  const current = repos ?? (github?.config.allowed_repos ?? []).join("\n");
  const pullRequests = prs ?? github?.config.pull_requests === true;

  async function save() {
    setError(undefined);
    setSaved(false);
    try {
      await api(`/projects/${projectId}/integrations/github`, {
        method: "PUT",
        body: { allowed_repos: current.split(/[\s,]+/).filter(Boolean), pull_requests: pullRequests },
      });
      setSaved(true);
      project.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    }
  }

  if (!project.data) return null;
  return (
    <Card title={<span>{project.data.name} <span className="font-mono text-xs text-muted">{project.data.key}</span></span>}>
      <div className="flex flex-col gap-2">
        <label className="text-sm text-muted" htmlFor={`repos-${projectId}`}>
          Authorized GitHub repositories (read-only, one owner/name per line)
        </label>
        <textarea
          id={`repos-${projectId}`}
          rows={2}
          value={current}
          onChange={(e) => setRepos(e.target.value)}
          className={`${inputClass} font-mono`}
        />
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={pullRequests}
            disabled={!canAct}
            onChange={(e) => setPrs(e.target.checked)}
            className="mt-1"
          />
          <span>
            Allow approved changes to open <strong>draft pull requests</strong> on GitHub
            <span className="block text-xs text-muted">
              Needs the GitHub App. Each PR still requires your approval; nothing is ever merged.
            </span>
          </span>
        </label>
        <ErrorNote message={error} />
        {canAct && (
          <div className="flex items-center justify-end gap-3">
            {saved && <span className="text-sm text-cyan">Saved</span>}
            <Button variant="ghost" onClick={save}>Save</Button>
          </div>
        )}
      </div>
    </Card>
  );
}
