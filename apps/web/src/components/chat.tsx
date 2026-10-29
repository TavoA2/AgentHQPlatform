"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, ErrorNote, formatTime } from "@/components/ui";
import { api } from "@/lib/api";
import type { ChatMessage, ChatProposal, Task } from "@/lib/types";

const TASK_LINK = /(\/tasks\/[0-9a-f-]{36})/g;

/** Plain text only (never HTML); task paths become links. */
function MessageText({ text }: { text: string }) {
  return (
    <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
      {text.split(TASK_LINK).map((part, i) =>
        i % 2 === 1 ? (
          <Link key={i} href={part} className="text-cyan underline-offset-2 hover:underline">
            {part}
          </Link>
        ) : (
          part
        ),
      )}
    </p>
  );
}

function ToolChips({ message }: { message: ChatMessage }) {
  if (!message.tool_calls.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Tools used">
      {message.tool_calls.map((call, i) => (
        <span
          key={i}
          title={call.error ?? JSON.stringify(call.arguments)}
          className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
            call.ok ? "border-border text-muted" : "border-orange/50 text-orange"
          }`}
        >
          {call.name.replace("chat.", "")}
          {call.denied ? " · denied" : call.ok ? "" : " · error"}
        </span>
      ))}
    </div>
  );
}

function ProposalCard({
  proposal,
  acceptUrl,
  canAct,
  onAccepted,
}: {
  proposal: ChatProposal;
  acceptUrl: string;
  canAct: boolean;
  onAccepted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function accept(start: boolean) {
    setBusy(true);
    setError(undefined);
    try {
      await api<Task>(acceptUrl, { method: "POST", body: { start } });
      onAccepted();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border border-violet/40 bg-background/60 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-violet">
          Task proposal · {proposal.project_key}
        </span>
        {proposal.status === "accepted" && proposal.task_id && (
          <Link href={`/tasks/${proposal.task_id}`} className="text-xs text-cyan">
            Created → open task
          </Link>
        )}
      </div>
      <p className="text-sm font-medium">{proposal.title}</p>
      <p className="whitespace-pre-wrap text-xs text-muted">{proposal.request}</p>
      {proposal.acceptance_criteria.length > 0 && (
        <ul className="list-disc pl-5 text-xs text-muted">
          {proposal.acceptance_criteria.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
      <ErrorNote message={error} />
      {proposal.status === "proposed" && canAct && (
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy} onClick={() => accept(true)}>
            Create and start
          </Button>
          <Button variant="ghost" disabled={busy} onClick={() => accept(false)}>
            Create as draft
          </Button>
        </div>
      )}
    </div>
  );
}

export function MessageBubble({
  message,
  conversationId,
  canAct,
  onChanged,
}: {
  message: ChatMessage;
  conversationId: string;
  canAct: boolean;
  onChanged: () => void;
}) {
  if (message.role === "user") {
    return (
      <div className="ml-auto max-w-[85%] rounded-lg rounded-br-sm bg-cyan/15 px-3 py-2">
        <MessageText text={message.content} />
      </div>
    );
  }
  return (
    <div className="mr-auto flex max-w-[90%] flex-col gap-2 rounded-lg rounded-bl-sm border border-border bg-surface px-3 py-2">
      <span className="font-mono text-[11px] uppercase tracking-wider text-violet">
        Dixon
        {message.alert_kind && (
          <span className="ml-2 text-orange">· alert · {message.alert_kind.replaceAll("_", " ")} · {formatTime(message.created_at)}</span>
        )}
      </span>
      {message.status === "pending" && (
        <p className="animate-pulse text-sm text-muted" aria-live="polite">
          Dixon is checking…
        </p>
      )}
      {message.status === "failed" && <ErrorNote message={message.error ?? "Dixon could not answer."} />}
      {message.content && <MessageText text={message.content} />}
      {message.proposals.map((p) => (
        <ProposalCard
          key={p.id}
          proposal={p}
          canAct={canAct}
          onAccepted={onChanged}
          acceptUrl={`/conversations/${conversationId}/messages/${message.id}/proposals/${p.id}/accept`}
        />
      ))}
      <ToolChips message={message} />
      {message.model_name && message.status !== "pending" && (
        <span className="font-mono text-[10px] text-muted">
          {message.model_provider}:{message.model_name} · {message.tokens_in + message.tokens_out} tokens
          {message.cost_usd ? ` · $${Number(message.cost_usd).toFixed(4)}` : ""}
        </span>
      )}
    </div>
  );
}
