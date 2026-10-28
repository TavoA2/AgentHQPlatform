import type { AgentStatus, ApprovalStatus, TaskStatus } from "@/lib/types";

const TASK_TONE: Record<TaskStatus, string> = {
  DRAFT: "border-border text-muted",
  PLANNED: "border-border text-muted",
  QUEUED: "border-blue-400/40 text-blue-300",
  RUNNING: "border-cyan/50 text-cyan",
  WAITING_APPROVAL: "border-orange/50 text-orange",
  IN_REVIEW: "border-violet/50 text-violet",
  COMPLETED: "border-emerald-400/50 text-emerald-300",
  FAILED: "border-rose-400/50 text-rose-300",
  CANCELLED: "border-border text-muted line-through",
};

const AGENT_TONE: Record<AgentStatus, string> = {
  IDLE: "border-border text-muted",
  RUNNING: "border-cyan/50 text-cyan",
  WAITING_APPROVAL: "border-orange/50 text-orange",
  FAILED: "border-rose-400/50 text-rose-300",
};

const APPROVAL_TONE: Record<ApprovalStatus, string> = {
  pending: "border-orange/50 text-orange",
  approved: "border-emerald-400/50 text-emerald-300",
  rejected: "border-rose-400/50 text-rose-300",
  expired: "border-border text-muted",
  cancelled: "border-border text-muted",
};

function Pill({ tone, children }: { tone: string; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[11px] tracking-wide ${tone}`}
    >
      {children}
    </span>
  );
}

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  return <Pill tone={TASK_TONE[status]}>{status.replace("_", " ")}</Pill>;
}

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  return <Pill tone={AGENT_TONE[status]}>{status.replace("_", " ")}</Pill>;
}

export function ApprovalStatusBadge({ status }: { status: ApprovalStatus }) {
  return <Pill tone={APPROVAL_TONE[status]}>{status}</Pill>;
}

export function Card({
  title,
  actions,
  children,
  className = "",
}: {
  title?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border border-border bg-surface ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-4 border-b border-border px-4 py-3">
          <h2 className="text-sm font-medium text-foreground">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Button({
  variant = "primary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const styles = {
    primary: "bg-cyan/90 text-background hover:bg-cyan",
    ghost: "border border-border text-foreground hover:border-cyan/60",
    danger: "border border-rose-400/50 text-rose-300 hover:bg-rose-400/10",
  }[variant];
  return (
    <button
      {...props}
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    />
  );
}

export const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted focus:border-cyan/60 focus:outline-none";

export function ErrorNote({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-md border border-rose-400/40 bg-rose-400/10 px-3 py-2 text-sm text-rose-200">
      {message}
    </p>
  );
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" });
}
