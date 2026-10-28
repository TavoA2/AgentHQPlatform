"use client";

import { useState } from "react";
import { ApprovalCard } from "@/components/approval-card";
import { Card, ErrorNote, inputClass } from "@/components/ui";
import { useApi } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live-events";
import type { Approval } from "@/lib/types";

export default function ApprovalsPage() {
  const [status, setStatus] = useState("pending");
  const approvals = useApi<Approval[]>(`/approvals${status ? `?status=${status}` : ""}`);
  useLiveRefresh(approvals.reload, (e) => e.type.startsWith("approval_"));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Approvals</h1>
        <p className="text-sm text-muted">
          Each approval authorizes one exact action with the parameters shown, once.
        </p>
      </div>
      <Card
        title="Queue"
        actions={
          <select aria-label="Status" className={inputClass} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="pending">Pending</option>
            <option value="">All</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="expired">Expired</option>
          </select>
        }
      >
        <ErrorNote message={approvals.error} />
        <div className="flex flex-col gap-4">
          {approvals.data?.length ? (
            approvals.data.map((a) => <ApprovalCard key={a.id} approval={a} onDecided={approvals.reload} />)
          ) : (
            <p className="text-sm text-muted">{approvals.loading ? "Loading…" : "Nothing here."}</p>
          )}
        </div>
      </Card>
    </div>
  );
}
