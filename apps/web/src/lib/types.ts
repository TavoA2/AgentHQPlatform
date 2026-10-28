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
  config: { allowed_repos?: string[] };
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

export type TaskResult = {
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
  title: string;
  request: string;
  status: TaskStatus;
  assigned_agent_key: string | null;
  acceptance_criteria: string[];
  options: { model_override?: string };
  result: TaskResult | null;
  failure_reason: string | null;
  failure_detail: string | null;
  run_number: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type TaskDetail = Task & { executions: Execution[]; approvals: Approval[] };

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
