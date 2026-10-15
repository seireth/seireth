export type Status =
  | "queued"
  | "running"
  | "cancelling"
  | "recovering"
  | "completed"
  | "failed"
  | "cancelled";
export interface Page<T> {
  items: T[];
  has_more: boolean;
}
export interface Project {
  id: string;
  name: string;
  created_at: string;
}
export interface Target {
  id: string;
  project_id: string;
  name: string;
  image: string | null;
  url: string;
  kind: "docker" | "website";
  launch_profile?: string | null;
  network_profile?: string | null;
  trust_profile?: string | null;
}
export interface Plugin {
  id: string;
  name: string;
  description: string;
  version: string;
  rules: Record<string, "representation" | "document" | "cookie-observation" | "session" | "cookie-presence">;
}
export interface TargetImages {
  items: { image: string; id: string }[];
}
export interface CheckOutcome {
  rule_id: string;
  status: "passed" | "failed" | "skipped" | "inconclusive";
  reason: string;
}
export interface Result {
  execution_outcome: "completed" | "failed" | "cancelled" | "interrupted" | "not_started";
  sandbox_backend?: "docker" | "http";
  cleanup_verified: boolean;
  cleanup_reason?: string | null;
  completed_at?: string;
  attempt?: number;
  error?: string;
  error_kind?: "timeout" | "plugin_error" | "execution_error";
  failed_plugin?: string;
  execution?: {
    started_at: string;
    deadline_at: string;
    target: Target;
    plugins: { id: string; version: string }[];
  };
  finding_count: number;
  routes: RouteResult[];
  coverage: { complete: boolean };
  verdict: { policy: string; status: "pass" | "blocked"; reasons: string[] };
  partial: boolean;
  comparison: { status: "not_requested" | "unavailable" | "available"; reason?: string;
    baseline?: string; new?: string[][]; resolved?: string[][]; unchanged?: string[][] };
}
export interface RouteResult {
  id?: string | null;
  key: string; url: string; status: "completed" | "failed" | "unattempted";
  error?: string;
  response?: { status_code: number; media_type: string | null; url: string;
    redirects: { url: string; status_code: number }[] };
  finding_count: number;
  plugins: { id: string; finding_count: number; checks: CheckOutcome[] }[];
  coverage: { complete: boolean; expected_response: boolean; missing_checks: string[]; failed_checks: string[] };
}
export interface Profiles {
  requests: Record<string, { headers: Record<string, string>; secret_headers: Record<string, string>; follow_redirects: boolean }>;
  launches: Record<string, unknown>; networks: Record<string, unknown>; trusts: string[];
}
export interface FrozenPlan {
  version: 1;
  target: Target & { launch_profile: string | null; network_profile: string | null; trust_profile: string | null };
  routes: {
    key: string; url: string; plugins: string[]; request_profile: string | null;
    request: Profiles["requests"][string]; request_seconds: number;
    expected: { statuses: number[]; media_types: string[]; final_url: string };
    required_checks: string[]; required_checks_explicit: boolean;
    analysis: { session_cookies: string[]; expected_cookies: string[] };
  }[];
  plugins: { id: string; version: string }[];
  images: Record<string, string>; launch: Record<string, unknown> | null;
  network: { url: string; cidrs: string[] } | null;
  ca: string | null; ca_fingerprint: string | null;
  control_endpoints: { address: string; port: number }[];
  timeout_seconds: number; cleanup_seconds: number;
  runner_limits: { memory: string; cpus: number; pids: number };
  policy: "strict-v1"; baseline: string | null;
}
export interface Assessment {
  id: string;
  project_id: string;
  target_id: string;
  url: string;
  created_at: string;
  status: Status;
  plugins: string[];
  cleanup_pending: boolean;
  result: Result | null;
  plan_snapshot: FrozenPlan;
}
export interface Finding {
  id: string;
  plugin: string;
  title: string;
  severity: string;
  description: string;
  remediation: string;
  route_result_id: string;
}
export interface Results {
  assessment_id: string;
  status: Status;
  cleanup_pending: boolean;
  result: Result | null;
  findings: Finding[];
}
type HeaderData = {
  url: string;
  header:
    | "x-content-type-options"
    | "content-security-policy"
    | "x-frame-options";
  rule_id:
    | "x-content-type-options"
    | "content-security-policy"
    | "framing-protection";
  status_code: number;
  media_type: string | null;
  condition: "missing" | "blank" | "unrecognized" | "unrestricted";
  expected:
    | "nosniff"
    | "nonblank enforced CSP"
    | "recognized restrictive framing protection";
};
export type CspContext = "network-script" | "inline-script" | "script-attribute" | "eval";
export type CspCondition =
  | "missing-directive" | "wildcard-source" | "http-scheme-source"
  | "https-scheme-source" | "global-host-source" | "unsafe-inline" | "unsafe-eval";
export type CspData = {
  url: string;
  header: "content-security-policy";
  rule_id: "csp-script-sources" | "csp-inline-scripts" | "csp-eval";
  status_code: number;
  media_type: string;
  policy_count: number;
  observations: {
    policy_index: number;
    context: CspContext;
    directive: "script-src-elem" | "script-src-attr" | "script-src" | "default-src" | null;
    condition: CspCondition;
  }[];
};
type CookieData = {
  url: string;
  header: "set-cookie";
  cookie_name: string;
  secure: boolean;
};
export type EvidenceData =
  | HeaderData
  | CspData
  | (CookieData & { rule_id: "samesite-none-without-secure"; samesite: "none" })
  | (CookieData & { rule_id: "secure-prefix"; https: boolean })
  | (CookieData & {
      rule_id: "host-prefix";
      https: boolean;
      domain_present: boolean;
      root_path: boolean;
    })
  | (CookieData & { rule_id: "session-cookie-secure" | "session-cookie-httponly"; httponly: boolean });
export interface Evidence {
  id: string;
  finding_id: string;
  kind: "http-response";
  data: EvidenceData;
}
export interface EvidenceResponse {
  assessment_id: string;
  status: Status;
  cleanup_pending: boolean;
  evidence: Evidence[];
}
export interface AssessmentReport {
  schema_version: 1;
  generated_at: string;
  project: Project;
  target: Target;
  assessment: Assessment & { result: Result };
  findings: Finding[];
  evidence: Evidence[];
}
export interface Audit {
  id: string;
  action: string;
  resource_id: string;
  created_at: string;
  details: Record<string, unknown>;
}
