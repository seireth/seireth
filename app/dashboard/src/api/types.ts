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
  image: string;
  url: string;
}
export interface Plugin {
  id: string;
  name: string;
  description: string;
}
export interface Runtime {
  sandbox_backend: "inmemory" | "docker";
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
  sandbox_backend?: string;
  cleanup_verified?: boolean;
  cleanup_reason?: string | null;
  completed_at?: string;
  attempt?: number;
  error?: string;
  finding_count?: number;
  response?: { status_code: number; media_type: string | null };
  plugins?: { id: string; finding_count: number; checks?: CheckOutcome[] }[];
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
}
export interface Finding {
  id: string;
  plugin: string;
  title: string;
  severity: string;
  description: string;
  remediation: string;
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
  | (CookieData & { rule: "samesite-none-without-secure"; samesite: "none" })
  | (CookieData & { rule: "secure-prefix"; https: boolean })
  | (CookieData & {
      rule: "host-prefix";
      https: boolean;
      domain_present: boolean;
      root_path: boolean;
    });
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
  schema_version: 2;
  generated_at: string;
  project: Project;
  target: Target;
  assessment: Assessment;
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
