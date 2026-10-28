"use client";

import Link from "next/link";
import { useState } from "react";
import { ApprovalStatusBadge, Button, ErrorNote, formatTime, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import type { Approval } from "@/lib/types";

/** Shows exactly what is being approved; the decision applies to this action only. */
export function ApprovalCard({ approval, onDecided }: { approval: Approval; onDecided: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const files = approval.evidence.files_inspected ?? [];

  async function decide(decision: "approve" | "reject") {
    setBusy(true);
    setError(undefined);
    try {
      await api(`/approvals/${approval.id}/${decision}`, { method: "POST", body: { note: note || null } });
      onDecided();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="rounded-lg border border-orange/30 bg-background/60 p-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-mono text-sm text-orange">{approval.action_type}</p>
          <p className="text-xs text-muted">
            requested by <span className="text-foreground">{approval.requested_by_agent_key}</span> ·{" "}
            <Link href={`/tasks/${approval.task_id}`} className="text-cyan hover:underline">task</Link>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-muted">risk: {approval.risk_level}</span>
          <ApprovalStatusBadge status={approval.status} />
        </div>
      </header>
      <dl className="mt-3 grid gap-x-4 gap-y-2 text-sm md:grid-cols-[10rem_1fr]">
        <dt className="text-muted">Target</dt>
        <dd className="break-all font-mono">{approval.target}</dd>
        <dt className="text-muted">Justification</dt>
        <dd>{approval.justification}</dd>
        <dt className="text-muted">Expected impact</dt>
        <dd>{approval.expected_impact}</dd>
        <dt className="text-muted">Exact parameters</dt>
        <dd>
          <pre className="overflow-x-auto rounded bg-surface p-2 font-mono text-xs">
            {JSON.stringify(approval.parameters, null, 2)}
          </pre>
        </dd>
        <dt className="text-muted">Evidence</dt>
        <dd className="text-xs">
          {approval.evidence.verification?.passed ? "Verification passed · " : ""}
          {files.length} files inspected: {files.map((f) => f.path).join(", ") || "—"}
        </dd>
        <dt className="text-muted">Action hash</dt>
        <dd className="break-all font-mono text-xs text-muted">{approval.action_hash}</dd>
        <dt className="text-muted">Expires</dt>
        <dd>{formatTime(approval.expires_at)}</dd>
      </dl>
      {approval.status === "pending" && (
        <div className="mt-4 flex flex-col gap-2">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Decision note (optional)"
            maxLength={2000}
            className={inputClass}
          />
          <ErrorNote message={error} />
          <div className="flex justify-end gap-2">
            <Button variant="danger" disabled={busy} onClick={() => decide("reject")}>Reject</Button>
            <Button disabled={busy} onClick={() => decide("approve")}>Approve this action</Button>
          </div>
        </div>
      )}
      {approval.status !== "pending" && approval.decision_note && (
        <p className="mt-3 text-sm text-muted">Note: {approval.decision_note}</p>
      )}
    </article>
  );
}
