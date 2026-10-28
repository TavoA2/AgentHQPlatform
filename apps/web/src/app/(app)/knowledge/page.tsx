"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, Card, ErrorNote, formatTime, inputClass } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import {
  KNOWLEDGE_KINDS,
  type Agent,
  type KnowledgeDetail,
  type KnowledgeDoc,
  type KnowledgeHit,
  type KnowledgeTrust,
  type Project,
} from "@/lib/types";

const TRUST_TONE: Record<KnowledgeTrust, string> = {
  approved: "border-emerald-400/50 text-emerald-300",
  unverified: "border-orange/50 text-orange",
  rejected: "border-rose-400/50 text-rose-300",
  archived: "border-border text-muted",
};

function TrustBadge({ trust }: { trust: KnowledgeTrust }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 font-mono text-[11px] ${TRUST_TONE[trust]}`}>{trust}</span>
  );
}

/** Renders «highlighted» search terms without injecting HTML. */
function Snippet({ text }: { text: string }) {
  const parts = text.split(/(«[^»]*»)/g);
  return (
    <p className="text-sm text-muted">
      {parts.map((p, i) =>
        p.startsWith("«") ? (
          <mark key={i} className="bg-cyan/20 text-foreground">{p.slice(1, -1)}</mark>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </p>
  );
}

export default function KnowledgePage() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("");
  const [trust, setTrust] = useState("");
  const [projectId, setProjectId] = useState("");
  const [selected, setSelected] = useState<string>();
  const [creating, setCreating] = useState(false);

  const params = new URLSearchParams({ limit: "100" });
  if (query) params.set("q", query);
  if (scope) params.set("scope", scope);
  if (trust) params.set("trust", trust);
  if (projectId) params.set("project_id", projectId);
  const hits = useApi<KnowledgeHit[]>(`/knowledge?${params}`);
  const projects = useApi<Project[]>("/projects");
  const agents = useApi<Agent[]>("/agents");
  const projectName = new Map(projects.data?.map((p) => [p.id, p.name]));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">The Brain</h1>
          <p className="text-sm text-muted">
            Company and project knowledge. Agents only see company knowledge and their task&apos;s
            project; what they write stays <span className="text-orange">unverified</span> until you
            approve it.
          </p>
        </div>
        <Button onClick={() => { setCreating(true); setSelected(undefined); }}>New entry</Button>
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); setQuery(q); }}
        className="grid gap-2 md:grid-cols-[2fr_1fr_1fr_1fr_auto]"
      >
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search (Spanish or English)…" className={inputClass} />
        <select aria-label="Scope" value={scope} onChange={(e) => setScope(e.target.value)} className={inputClass}>
          <option value="">All scopes</option>
          <option value="company">Company</option>
          <option value="project">Project</option>
        </select>
        <select aria-label="Project" value={projectId} onChange={(e) => setProjectId(e.target.value)} className={inputClass}>
          <option value="">All projects</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select aria-label="Trust" value={trust} onChange={(e) => setTrust(e.target.value)} className={inputClass}>
          <option value="">Any trust</option>
          <option value="unverified">Unverified (to review)</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="archived">Archived</option>
        </select>
        <Button type="submit" variant="ghost">Search</Button>
      </form>

      {creating && (
        <Editor
          projects={projects.data ?? []}
          agents={agents.data ?? []}
          onDone={(id) => { setCreating(false); hits.reload(); if (id) setSelected(id); }}
        />
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card title={`Entries (${hits.data?.length ?? 0})`}>
          <ErrorNote message={hits.error} />
          <ul className="flex flex-col divide-y divide-border">
            {hits.data?.map((h) => (
              <li key={h.id}>
                <button
                  onClick={() => { setSelected(h.id); setCreating(false); }}
                  className={`w-full py-3 text-left ${selected === h.id ? "text-cyan" : ""}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{h.title}</span>
                    <TrustBadge trust={h.trust} />
                  </div>
                  <p className="font-mono text-xs text-muted">
                    {h.scope === "company" ? "company" : projectName.get(h.project_id ?? "") ?? "project"} · {h.kind}
                    {h.created_by_agent ? ` · by ${h.created_by_agent}` : ""}
                  </p>
                  <Snippet text={h.snippet} />
                </button>
              </li>
            ))}
            {!hits.loading && !hits.data?.length && <li className="py-3 text-sm text-muted">Nothing found.</li>}
          </ul>
        </Card>
        {selected && (
          <Detail
            id={selected}
            agents={agents.data ?? []}
            projectName={projectName}
            onChanged={hits.reload}
          />
        )}
      </div>
    </div>
  );
}

function Detail({
  id,
  agents,
  projectName,
  onChanged,
}: {
  id: string;
  agents: Agent[];
  projectName: Map<string, string>;
  onChanged: () => void;
}) {
  const doc = useApi<KnowledgeDetail>(`/knowledge/${id}`);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string>();

  async function review(action: "approve" | "reject" | "archive") {
    setError(undefined);
    try {
      await api(`/knowledge/${id}/${action}`, { method: "POST", body: {} });
      doc.reload();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  if (!doc.data) return <Card title="Entry"><p className="text-sm text-muted">Loading…</p></Card>;
  const d = doc.data;
  if (editing) {
    return (
      <Editor
        existing={d}
        projects={[]}
        agents={agents}
        onDone={() => { setEditing(false); doc.reload(); onChanged(); }}
      />
    );
  }
  return (
    <Card
      title={d.title}
      actions={
        <div className="flex items-center gap-2">
          <TrustBadge trust={d.trust} />
          <span className="font-mono text-xs text-muted">v{d.version}</span>
        </div>
      }
    >
      <dl className="mb-3 grid grid-cols-[7rem_1fr] gap-y-1 text-xs">
        <dt className="text-muted">Scope</dt>
        <dd>{d.scope === "company" ? "Company" : `Project · ${projectName.get(d.project_id ?? "") ?? d.project_id}`}</dd>
        <dt className="text-muted">Kind</dt>
        <dd>{d.kind}</dd>
        <dt className="text-muted">Author</dt>
        <dd>{d.created_by_agent ? `agent ${d.created_by_agent}` : "you"}</dd>
        {d.source_task_id && (
          <>
            <dt className="text-muted">Source task</dt>
            <dd><Link href={`/tasks/${d.source_task_id}`} className="text-cyan">open task</Link></dd>
          </>
        )}
        <dt className="text-muted">Visible to</dt>
        <dd>{d.audience.length ? d.audience.join(", ") : "all agents"}</dd>
        <dt className="text-muted">Updated</dt>
        <dd>{formatTime(d.updated_at)}</dd>
      </dl>
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded bg-background p-3 text-sm">{d.content}</pre>
      <ErrorNote message={error} />
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        {d.trust !== "approved" && <Button onClick={() => review("approve")}>Approve as fact</Button>}
        {d.trust === "unverified" && <Button variant="danger" onClick={() => review("reject")}>Reject</Button>}
        {d.trust !== "archived" && <Button variant="ghost" onClick={() => review("archive")}>Archive</Button>}
        <Button variant="ghost" onClick={() => setEditing(true)}>Edit</Button>
      </div>
      <details className="mt-4 text-sm">
        <summary className="cursor-pointer text-muted">History ({d.versions.length} versions)</summary>
        <ol className="mt-2 flex flex-col gap-2">
          {d.versions.map((v) => (
            <li key={v.version} className="rounded border border-border p-2 text-xs">
              <span className="font-mono">v{v.version}</span> · <TrustBadge trust={v.trust} /> ·{" "}
              {v.changed_by_agent ? `agent ${v.changed_by_agent}` : "you"} · {formatTime(v.created_at)}
              {v.note ? ` · “${v.note}”` : ""}
            </li>
          ))}
        </ol>
      </details>
    </Card>
  );
}

function Editor({
  existing,
  projects,
  agents,
  onDone,
}: {
  existing?: KnowledgeDoc;
  projects: Project[];
  agents: Agent[];
  onDone: (id?: string) => void;
}) {
  const [scope, setScope] = useState<"company" | "project">(existing?.scope ?? "company");
  const [audience, setAudience] = useState<string[]>(existing?.audience ?? []);
  const [error, setError] = useState<string>();

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const tags = String(f.get("tags") ?? "").split(",").map((t) => t.trim()).filter(Boolean);
    setError(undefined);
    try {
      if (existing) {
        await api(`/knowledge/${existing.id}`, {
          method: "PUT",
          body: { title: f.get("title"), content: f.get("content"), audience, tags, note: f.get("note") || null },
        });
        onDone(existing.id);
      } else {
        const doc = await api<KnowledgeDoc>("/knowledge", {
          method: "POST",
          body: {
            scope,
            project_id: scope === "project" ? f.get("project_id") : null,
            kind: f.get("kind"),
            title: f.get("title"),
            content: f.get("content"),
            audience,
            tags,
          },
        });
        onDone(doc.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    }
  }

  return (
    <Card title={existing ? `Edit · ${existing.title}` : "New knowledge entry"}>
      <form onSubmit={onSubmit} className="grid gap-3">
        {!existing && (
          <div className="grid gap-3 md:grid-cols-3">
            <select aria-label="Scope" value={scope} onChange={(e) => setScope(e.target.value as "company" | "project")} className={inputClass}>
              <option value="company">Company</option>
              <option value="project">Project</option>
            </select>
            {scope === "project" && (
              <select name="project_id" aria-label="Project" required className={inputClass}>
                {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            )}
            <select name="kind" aria-label="Kind" defaultValue="note" className={inputClass}>
              {KNOWLEDGE_KINDS.filter((k) => k !== "execution_summary").map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </div>
        )}
        <input name="title" required maxLength={200} defaultValue={existing?.title} placeholder="Title" className={inputClass} />
        <textarea name="content" required rows={8} defaultValue={existing?.content} placeholder="Content (no secrets or credentials)" className={inputClass} />
        <input name="tags" defaultValue={existing?.tags.join(", ")} placeholder="Tags, comma separated" className={inputClass} />
        <fieldset className="flex flex-wrap items-center gap-3 text-sm">
          <legend className="mb-1 text-muted">Visible to (none checked = all agents)</legend>
          {agents.map((a) => (
            <label key={a.key} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={audience.includes(a.key)}
                onChange={(e) =>
                  setAudience(e.target.checked ? [...audience, a.key] : audience.filter((k) => k !== a.key))
                }
              />
              {a.display_name}
            </label>
          ))}
        </fieldset>
        {existing && <input name="note" placeholder="Change note (optional)" className={inputClass} />}
        <ErrorNote message={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => onDone(existing?.id)}>Cancel</Button>
          <Button type="submit">{existing ? "Save new version" : "Create"}</Button>
        </div>
      </form>
    </Card>
  );
}
