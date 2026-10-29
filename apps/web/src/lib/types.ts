// Mirrors apps/api/src/agent_hq/api/schemas.py. Keep in sync until types are generated
// from the OpenAPI schema.

export type TaskStatus =
  | "DRAFT"
  | "PLANNED"
  | "QUEUED"
  | "RUNNING"
  | "WAITING_APPROVAL"
  | "IN_REVIEW"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export const TASK_STATUSES: TaskStatus[] = [
  "DRAFT",
  "PLANNED",
  "QUEUED",
  "RUNNING",
  "WAITING_APPROVAL",
  "IN_REVIEW",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
];

export type AgentStatus = "IDLE" | "RUNNING" | "WAITING_APPROVAL" | "FAILED";
export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired" | "cancelled";

export type User = { id: string; email: string; display_name: string; role: string };
export type Session = { user: User; csrf_token: string };

export type Integration = {
  id: string;
  provider: string;
  name: string;
  config: { allowed_repos?: string[]; pull_requests?: boolean };
  secret_ref: string | null;
  scopes: string[];
  enabled: boolean;
};

export type Project = {
  id: string;
  key: string;
  name: string;
  description: string;
  client_name: string | null;
  status: string;
  created_at: string;
};

export type ProjectDetail = Project & { integrations: Integration[] };

export type Execution = {
  id: string;
  agent_key: string;
  run_number: number;
  attempt: number;
  status: "running" | "succeeded" | "failed" | "cancelled";
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  model_provider: string | null;
  model_name: string | null;
  model_calls: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: string | null;
  started_at: string;
  finished_at: string | null;
};

export type Approval = {
  id: string;
  task_id: string;
  project_id: string;
  requested_by_agent_key: string;
  action_type: string;
  target: string;
  parameters: Record<string, unknown>;
  action_hash: string;
  justification: string;
  expected_impact: string;
  risk_level: "low" | "medium" | "high" | "critical";
  evidence: {
    files_inspected?: { path: string; sha: string; size: number }[];
    verification?: { passed: boolean; problems: string[] };
    report_sha256?: string;
  };
  status: ApprovalStatus;
  decision_note: string | null;
  decided_at: string | null;
  expires_at: string;
  consumed_at: string | null;
  created_at: string;
};

export type Finding = {
  severity: "low" | "medium" | "high" | "critical";
  category: string;
  file: string;
  line_start: number | null;
  line_end: number | null;
  description: string;
};

export type Recommendation = {
  title: string;
  rationale: string;
  proposed_change: string;
  effort: string;
  risk: string;
};

export type ChangedFile = { path: string; action: "create" | "modify"; content: string };

export type Changeset = {
  summary: string;
  rationale: string;
  files: ChangedFile[];
  tests: ChangedFile[];
  risks: string[];
  repository: string;
  files_read: string[];
};

export type SandboxRun = {
  exit_code: number | null;
  timed_out: boolean;
  duration_ms: number;
  output: string;
  summary: { passed: number; failed: number; errors: number } | null;
};

export type QaResult = {
  report: { verdict: "ready" | "not_ready"; summary: string; failures: string[] };
  sandbox: SandboxRun | null;
};

export type TestPlan = { cases: { name: string; description: string; expected: string }[] };

export type TaskResult = {
  workflow?: "cicd_review" | "code_change";
  changeset?: Changeset;
  test_plan?: TestPlan;
  qa?: QaResult;
  summary?: { outcome: string; risks: string[]; next_steps: string[] };
  recommendation?: {
    repository: string;
    files_inspected: { path: string; sha: string; size: number }[];
    findings: Finding[];
    recommendations: Recommendation[];
    limitations: string[];
  };
  verification?: { passed: boolean; problems: string[] };
  publication?: { published: boolean; location: string; mock: boolean } | null;
};

export type Task = {
  id: string;
  project_id: string;
  parent_task_id: string | null;
  title: string;
  request: string;
  status: TaskStatus;
  assigned_agent_key: string | null;
  acceptance_criteria: string[];
  options: { model_override?: string; step_id?: string; kind?: string; depends_on?: string[] };
  result: TaskResult | null;
  failure_reason: string | null;
  failure_detail: string | null;
  run_number: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type TaskDetail = Task & {
  executions: Execution[];
  approvals: Approval[];
  subtasks: Task[];
};

export type MetricsSummary = {
  generated_at: string;
  window_hours: number;
  tasks_by_status: Record<string, number>;
  subtasks_by_status: Record<string, number>;
  jobs_by_status: Record<string, number>;
  recent_failed_jobs: {
    id: number;
    task_id: string | null;
    kind: string;
    attempts: number;
    last_error: string | null;
    updated_at: string;
  }[];
  approvals_pending: number;
  approval_median_seconds: number | null;
  agents: {
    key: string;
    executions: number;
    failed: number;
    running: number;
    tokens_in: number;
    tokens_out: number;
    cost_usd: string | null;
  }[];
};

export type TaskEvent = {
  id: number;
  task_id: string;
  project_id: string;
  execution_id: string | null;
  agent_key: string | null;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type Agent = {
  key: string;
  display_name: string;
  department: string;
  description: string;
  model_profile: string;
  enabled: boolean;
  status: AgentStatus;
  current_task_id: string | null;
  last_execution: Execution | null;
  allowed_tools: string[];
};

export type KnowledgeTrust = "approved" | "unverified" | "rejected" | "archived";

export const KNOWLEDGE_KINDS = [
  "company_profile",
  "service",
  "policy",
  "brand",
  "procedure",
  "decision",
  "requirement",
  "architecture",
  "constraint",
  "note",
  "execution_summary",
] as const;

export type KnowledgeDoc = {
  id: string;
  scope: "company" | "project";
  project_id: string | null;
  kind: string;
  title: string;
  content: string;
  trust: KnowledgeTrust;
  audience: string[];
  tags: string[];
  version: number;
  created_by_user_id: string | null;
  created_by_agent: string | null;
  source_task_id: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type KnowledgeHit = KnowledgeDoc & { rank: number; snippet: string };

export type KnowledgeVersion = {
  version: number;
  title: string;
  content: string;
  trust: KnowledgeTrust;
  changed_by_user_id: string | null;
  changed_by_agent: string | null;
  source_task_id: string | null;
  note: string | null;
  created_at: string;
};

export type KnowledgeDetail = KnowledgeDoc & { versions: KnowledgeVersion[] };

export type AgentActivity = {
  execution: Execution;
  task_id: string;
  task_title: string;
  task_status: TaskStatus;
  parent_task_id: string | null;
};

export type AgentDetail = Agent & { recent_activity: AgentActivity[]; pending_approvals: number };

// --- chat with Dixon (ADR-0015) ---
export type ChatProposal = {
  id: string;
  project_id: string;
  project_key: string;
  title: string;
  request: string;
  acceptance_criteria: string[];
  status: "proposed" | "accepted";
  task_id: string | null;
};

export type ChatToolCall = {
  name: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  denied: boolean;
  error: string | null;
};

export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  status: "pending" | "complete" | "failed";
  alert_kind: string | null;
  tool_calls: ChatToolCall[];
  proposals: ChatProposal[];
  error: string | null;
  model_provider: string | null;
  model_name: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_usd: string | null;
  created_at: string;
  completed_at: string | null;
};

export type Conversation = {
  id: string;
  project_id: string | null;
  title: string;
  kind: "chat" | "alerts";
  created_at: string;
  updated_at: string;
};

export type ConversationDetail = Conversation & { messages: ChatMessage[] };

export type AlertsStatus = { conversation_id: string | null; unread: number };

/** Fired after alerts are marked read so the header badge refreshes at once. */
export const ALERTS_READ_EVENT = "agent-hq:alerts-read";
