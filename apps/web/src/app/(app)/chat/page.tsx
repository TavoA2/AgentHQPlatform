"use client";

import { useEffect, useRef, useState } from "react";
import { MessageBubble } from "@/components/chat";
import { Button, Card, ErrorNote, formatTime, inputClass } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { useCanAct } from "@/lib/session";
import type { Conversation, ConversationDetail, Project } from "@/lib/types";

const POLL_MS = 1500;

export default function ChatPage() {
  const canAct = useCanAct();
  const conversations = useApi<Conversation[]>("/conversations");
  const projects = useApi<Project[]>("/projects");
  const [selected, setSelected] = useState<string | null>(null);
  const [scope, setScope] = useState("");
  const [error, setError] = useState<string>();
  const activeId = selected ?? conversations.data?.[0]?.id ?? null;
  const projectKey = (id: string | null) =>
    id ? (projects.data?.find((p) => p.id === id)?.key ?? "project") : "company-wide";

  async function create() {
    setError(undefined);
    try {
      const c = await api<Conversation>("/conversations", {
        method: "POST",
        body: { project_id: scope || null },
      });
      setSelected(c.id);
      conversations.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Dixon</h1>
        <p className="text-sm text-muted">
          Ask Dixon about projects, tasks, approvals, the team and The Brain. Dixon can propose
          work, but nothing is created or run until you confirm it.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-[260px_1fr]">
        <Card title="Conversations">
          <div className="flex flex-col gap-3">
            {canAct && (
              <div className="flex flex-col gap-2">
                <select
                  aria-label="Conversation scope"
                  className={inputClass}
                  value={scope}
                  onChange={(e) => setScope(e.target.value)}
                >
                  <option value="">Company-wide</option>
                  {projects.data
                    ?.filter((p) => p.status === "active")
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        Project: {p.name}
                      </option>
                    ))}
                </select>
                <Button onClick={create}>New conversation</Button>
                <ErrorNote message={error} />
              </div>
            )}
            <ErrorNote message={conversations.error} />
            <ul className="flex flex-col gap-1">
              {conversations.data?.map((c) => (
                <li key={c.id}>
                  <button
                    onClick={() => setSelected(c.id)}
                    className={`w-full rounded-md px-2 py-1.5 text-left text-sm ${
                      c.id === activeId ? "bg-background text-foreground" : "text-muted hover:text-foreground"
                    }`}
                  >
                    <span className="block truncate">{c.title}</span>
                    <span className="font-mono text-[10px]">
                      {projectKey(c.project_id)} · {formatTime(c.updated_at)}
                    </span>
                  </button>
                </li>
              ))}
              {conversations.data?.length === 0 && (
                <li className="text-sm text-muted">No conversations yet.</li>
              )}
            </ul>
          </div>
        </Card>
        {activeId ? (
          <Thread
            key={activeId}
            conversationId={activeId}
            canAct={canAct}
            scopeLabel={projectKey}
            onActivity={conversations.reload}
          />
        ) : (
          <Card>
            <p className="text-sm text-muted">
              {conversations.loading ? "Loading…" : "Start a conversation to talk with Dixon."}
            </p>
          </Card>
        )}
      </div>
    </div>
  );
}

function Thread({
  conversationId,
  canAct,
  scopeLabel,
  onActivity,
}: {
  conversationId: string;
  canAct: boolean;
  scopeLabel: (projectId: string | null) => string;
  onActivity: () => void;
}) {
  const detail = useApi<ConversationDetail>(`/conversations/${conversationId}`);
  const { reload } = detail;
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();
  const bottom = useRef<HTMLDivElement>(null);
  const messages = detail.data?.messages ?? [];
  const pending = messages.some((m) => m.status === "pending");

  // Dixon answers in the worker; poll only while a reply is pending (ADR-0015).
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(reload, POLL_MS);
    return () => clearInterval(timer);
  }, [pending, reload]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length, pending]);

  async function send() {
    const content = draft.trim();
    if (!content) return;
    setSending(true);
    setError(undefined);
    try {
      await api(`/conversations/${conversationId}/messages`, { method: "POST", body: { content } });
      setDraft("");
      reload();
      onActivity();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <Card
      title={detail.data?.title ?? "…"}
      actions={
        detail.data && (
          <span className="font-mono text-[11px] text-muted">scope: {scopeLabel(detail.data.project_id)}</span>
        )
      }
    >
      <div className="flex flex-col gap-4">
        <ErrorNote message={detail.error} />
        <div className="flex max-h-[60vh] min-h-[240px] flex-col gap-3 overflow-y-auto pr-1" aria-live="polite">
          {messages.length === 0 && !detail.loading && (
            <p className="text-sm text-muted">
              Try: “¿Qué tareas hay y qué espera mi aprobación?” or “Revisa el CI/CD de owner/repo”.
            </p>
          )}
          {messages.map((m) => (
            <MessageBubble
              key={m.id}
              message={m}
              conversationId={conversationId}
              canAct={canAct}
              onChanged={reload}
            />
          ))}
          <div ref={bottom} />
        </div>
        {canAct && (
          <form
            className="flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <textarea
              aria-label="Message to Dixon"
              className={`${inputClass} min-h-[72px] resize-y`}
              maxLength={4000}
              placeholder="Message Dixon… (Enter to send, Shift+Enter for a new line)"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <ErrorNote message={error} />
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-muted">
                Dixon reads real data; approvals stay on the Approvals page.
              </span>
              <Button type="submit" disabled={sending || pending || !draft.trim()}>
                {pending ? "Dixon is answering…" : "Send"}
              </Button>
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}
