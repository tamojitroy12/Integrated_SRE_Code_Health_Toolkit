// API shapes (docs/API_SPEC.md). Field names mirror the wire format.

export type Role = "viewer" | "maintainer" | "admin";
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type JobStatus = "queued" | "running" | "succeeded" | "partial" | "failed" | "cancelled";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: Role;
}

export interface AdminUser extends User {
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  total?: number;
}

export interface ProjectHealth {
  open_alerts: number;
  unacknowledged_alerts: number;
  last_scan_status: JobStatus | null;
  last_scan_at: string | null;
  has_repository: boolean;
  target_count: number;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  health: ProjectHealth | null;
}

export interface Repository {
  id: string;
  provider: string;
  owner: string;
  name: string;
  url: string;
  default_branch: string;
  ecosystems: string[];
  manifests: string[];
  has_token: boolean;
  can_open_prs: boolean;
  is_private: boolean;
  test_command: string | null;
  verified_at: string | null;
}

export type TargetStatus = "waiting" | "receiving" | "stale";

export interface Target {
  id: string;
  project_id: string;
  name: string;
  service_name: string;
  environment: string;
  ingestion_mode: string;
  status: TargetStatus;
  last_seen_at: string | null;
  created_at: string;
}

export interface Onboarding {
  otlp_http_endpoint: string;
  env: Record<string, string>;
  token_included: boolean;
  token_note: string;
  required_metric: string;
  notes: string[];
}

export type ChartMetric = "request_rate" | "error_ratio" | "latency_p50" | "latency_p95" | "latency_p99";
export type RangeKey = "15m" | "1h" | "6h" | "24h";

export interface MetricSeries {
  metric: ChartMetric;
  unit: string;
  range: RangeKey;
  step_seconds: number;
  status: "ok" | "no_data" | "no_traffic";
  target_status: TargetStatus;
  series: { t: string; v: number | null }[];
}

export interface CurrentValues {
  request_rate: number | null;
  error_ratio: number | null;
  latency_p95_seconds: number | null;
}

export interface SectionError {
  code: string;
  message: string;
}

export interface Overview {
  project: { id: string; name: string; description: string | null; archived_at: string | null };
  monitoring: {
    status: "ok" | "empty" | "error";
    error?: SectionError;
    targets: (Pick<Target, "id" | "name" | "service_name" | "environment" | "status" | "last_seen_at"> & {
      current: CurrentValues | null;
    })[];
  };
  alerts: {
    status: "ok" | "empty" | "error";
    error?: SectionError;
    open_count: number;
    unacknowledged_count: number;
    by_severity: Partial<Record<Severity, number>>;
    recent: { id: string; rule_name: string; severity: Severity; status: AlertStatus; last_seen_at: string;
      observed_value: number | null; threshold: number | null }[];
  };
  latest_scan: {
    status: "ok" | "empty" | "error";
    error?: SectionError;
    has_repository?: boolean;
    scan_id?: string;
    scan_status?: JobStatus;
    commit_sha?: string | null;
    created_at?: string;
    finished_at?: string | null;
    summary?: ScanSummary;
    providers?: { name: string; status: ProviderStatus; error: string | null }[];
  };
  top_findings: {
    status: "ok" | "empty" | "error";
    error?: SectionError;
    open_by_severity: Record<string, number>;
    items: { id: string; type: FindingType; title: string; severity: Severity | null; change: Change;
      package_name: string | null; file_path: string | null }[];
  };
  open_fix_proposals: number;
  server_timestamp: string;
}

export interface Summary {
  project_id: string;
  unacknowledged_alerts_count: number;
  open_alerts_count: number;
  last_scan_status: JobStatus | null;
  open_findings_counts: Record<string, number>;
  server_timestamp: string;
}

export type AlertStatus = "firing" | "acknowledged" | "resolved";
export type RuleType = "threshold" | "absence" | "anomaly";
export type RuleMetric = "error_ratio" | "latency_p95" | "request_rate" | "data_absent";

export interface AlertRule {
  id: string;
  project_id: string;
  target_id: string;
  name: string;
  type: RuleType;
  metric: RuleMetric;
  comparator: "gt" | "lt" | null;
  threshold: number | null;
  window: "1m" | "5m" | "15m" | null;
  duration_seconds: number;
  resolve_after: number;
  params: Record<string, number>;
  severity: Severity;
  guidance: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface Attribution {
  id: string;
  display_name: string;
}

export interface Alert {
  id: string;
  rule_id: string | null;
  rule_name: string;
  target_id: string | null;
  project_id: string;
  status: AlertStatus;
  severity: Severity;
  first_seen_at: string;
  last_seen_at: string;
  occurrence_count: number;
  evidence: {
    query: string;
    query_name?: string;
    observed_value: number | null;
    threshold: number | null;
    comparator?: string;
    window: string;
    guidance: string;
    evaluated_at?: string;
    z_score?: number;
    last_observed_value?: number | null;
    rule_type?: RuleType;
    metric?: RuleMetric;
    duration_seconds?: number;
  };
  acknowledged_by: Attribution | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  resolved_by: Attribution | null;
  target: { id: string; name: string; service_name: string; environment: string } | null;
}

export interface Delivery {
  id: string;
  channel_id: string;
  channel_name: string | null;
  event: string;
  status: "pending" | "delivered" | "failed" | "suppressed";
  http_status: number | null;
  error: string | null;
  attempts: number;
  attempted_at: string | null;
}

export interface Channel {
  id: string;
  type: "webhook" | "email";
  name: string;
  enabled: boolean;
  config: { host?: string; port?: number };
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  type: string;
  status: JobStatus;
  stage: string | null;
  attempts: number;
  error: { code: string; message: string | null } | null;
  resource: { type: string; id: string } | null;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export type ProviderStatus = "ok" | "failed" | "skipped";

export interface ScanSummary {
  dependencies?: number;
  new?: number;
  unchanged?: number;
  resolved?: number;
  findings?: number;
  by_type_severity?: Record<string, Record<string, number>>;
  warnings?: string[];
  failed_providers?: string[];
}

export interface Scan {
  id: string;
  project_id: string;
  status: JobStatus;
  ref: string;
  commit_sha: string | null;
  trigger: "manual" | "scheduled";
  requested_providers: string[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: { code: string; message: string } | null;
  providers: { name: string; status: ProviderStatus; duration_ms: number; error: string | null;
    tool_version: string | null; db_info: Record<string, string | null> | null }[];
  summary: ScanSummary;
  job: Job | null;
}

export type FindingType = "dependency_vulnerability" | "dependency_outdated" | "dependency_incompatibility" | "code_issue";
export type FindingStatus = "open" | "dismissed" | "resolved";
export type Change = "new" | "unchanged" | "resolved";

export interface FindingSummary {
  id: string;
  project_id: string;
  type: FindingType;
  title: string;
  severity: Severity | null;
  severity_source: string | null;
  status: FindingStatus;
  change: Change;
  fingerprint: string;
  subject: {
    ecosystem?: string | null; name?: string | null; version?: string | null; scope?: string | null;
    manifest_path?: string | null; file_path?: string | null; line_start?: number | null; line_end?: number | null;
    rule_id?: string | null;
  };
  advisory_ids: string[];
  sources: string[];
  dismissal_reason: string | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface EvidenceItem {
  id: string;
  kind: "advisory_record" | "registry_metadata" | "code_snippet" | "scanner_output";
  source: string;
  url: string | null;
  retrieved_at: string;
  content: Record<string, unknown>;
}

export interface FindingDetail extends FindingSummary {
  message: string | null;
  advisory: { ids?: string[]; fixed_versions?: string[]; recommended_fix?: string | null; summary?: string | null;
    references?: string[]; primary_id?: string } | null;
  detail: Record<string, unknown> | null;
  evidence: EvidenceItem[];
  last_seen_scan_id: string | null;
  resolved_at: string | null;
  dismissal: { reason: string; note: string | null; at: string; by: Attribution | null } | null;
  history: { scan_id: string; created_at: string; commit_sha: string | null; scan_status: JobStatus; change: string }[];
  recommendations: { id: string; kind: string; status: string; validation_status: ValidationStatus | null;
    created_at: string }[];
  fix_proposals: { id: string; status: ProposalStatus; validation_result: ValidationResult; pr_url: string | null;
    created_at: string }[];
  fixable: boolean;
}

export type ValidationStatus = "validated" | "partially_validated" | "rejected";
export type RecommendationKind = "library_alternative" | "upgrade_guidance" | "code_improvement";

export interface Claim {
  claim_id: string;
  type: string;
  kind: "checkable" | "judgment";
  text: string;
  evidence_refs: string[];
  validation: "supported" | "unsupported" | "unverifiable";
  validation_note: string;
}

export interface Recommendation {
  id: string;
  finding_id: string;
  kind: RecommendationKind;
  status: "pending" | "completed" | "failed";
  validation_status: ValidationStatus | null;
  model: string;
  summary: string | null;
  claims: Claim[];
  alternatives: { name: string; ecosystem: string; rationale: string; evidence_refs: string[];
    criteria: Record<string, string | number | null> }[];
  suggested_steps: string[];
  proposed_patch: string | null;
  confidence: "low" | "medium" | "high" | null;
  limitations: string[];
  evidence: { id: string; kind: string; source: string; url: string | null; retrieved_at: string | null }[];
  error: { code: string; message: string | null } | null;
  feedback: { rating: string; comment: string | null } | null;
  label: string;
  raw_output?: string | null;
  job: Job | null;
  created_at: string;
}

export type ProposalStatus = "pending" | "validating" | "ready" | "approved" | "pr_opened" | "rejected" | "failed"
  | "superseded";
export type ValidationResult = "passed" | "failed" | "unverified" | "not_run";

export interface ValidationRun {
  stage: string;
  status: "passed" | "failed" | "skipped" | "error";
  exit_code: number | null;
  duration_s: number;
  output_tail: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface ProposalChange {
  ecosystem: string;
  package: string;
  from_version: string;
  to_version: string;
  bump: string;
  manifest_path: string;
  lockfile_path: string;
  scope: string | null;
}

export interface FixProposal {
  id: string;
  project_id: string;
  status: ProposalStatus;
  finding_ids: string[];
  base_commit_sha: string | null;
  changes: ProposalChange[];
  has_major_bump: boolean;
  validation: {
    result: ValidationResult;
    baseline?: ValidationRun | null;
    apply?: ValidationRun | null;
    post_change?: ValidationRun | null;
    delta_scan?: { status?: string; resolved_finding_ids?: string[]; new_findings?: Record<string, string>[];
      unresolved?: Record<string, string>[] } | null;
    runs?: ValidationRun[];
  };
  pull_request: { number: number; url: string; draft: boolean; branch: string; closed_at: string | null } | null;
  pr_error: string | null;
  error: { code: string; message: string | null } | null;
  diff?: string | null;
  risk_notes?: string[];
  approval?: { by: Attribution | null; at: string; comment?: string | null; admin_override?: boolean } | null;
  repository?: { can_open_prs: boolean; url: string } | null;
  job: Job | null;
  created_at: string;
  updated_at: string;
}

export interface AuditEntry {
  id: string;
  action: string;
  actor: Attribution | null;
  resource_type: string | null;
  resource_id: string | null;
  metadata: Record<string, unknown>;
  ip: string | null;
  created_at: string;
}
