// Tipos que espelham as respostas da API (backend/app/api e app/domain/schemas.py).
export type Role = 'member' | 'manager';

export interface Membership { member_id: number; team_id: string; team_name: string; role: Role; name: string; }
export interface Me { email: string; name: string; dev_mode: boolean; must_change_password: boolean; memberships: Membership[]; }
export interface DevUser { email: string; name: string; roles: Role[]; }

export interface ImpedimentView {
  id: number; summary: string; category: string; severity: string; needs_from: string; reporter: string;
  member_id: number; status: string; age_days: number; age_label: string; aged: boolean; note: string;
}
export interface MemberStatus {
  member_id: number; name: string; email: string; role: Role; responded: boolean; confirmed_at: string | null;
}
export interface Today {
  cycle_id: string; date: string; responded: number; total: number; latest_report_id: number | null;
  team: { id: string; name: string; timezone: string; cutoff_time: string };
  members?: MemberStatus[]; impediments?: ImpedimentView[];
  resolved_today?: { id: number; summary: string; note: string }[]; aged_threshold_days?: number;
}

export interface Blocker {
  summary: string; category: string; severity: string; needs_from: string; existing_impediment_id: number | null;
}
export interface CheckinDraft {
  done: { summary: string; related_to_previous_plan: boolean }[];
  planned: { summary: string }[];
  blockers: Blocker[];
  resolved_impediment_ids: number[];
  risks: { summary: string; type: string }[];
  notes: string;
}
export interface CheckinContext {
  first_name: string;
  previous: { day: string; planned: string[] } | null;
  open_impediments: ImpedimentView[];
  today: { confirmed_at: string; version: number; data: CheckinDraft } | null;
}

export interface Recommendation {
  text: string; tag: string; high_priority: boolean; suggested_owner: string; evidence_ids: string[];
}
export interface ReportContent {
  actions: Recommendation[];
  progress: { theme: string; items: { text: string; evidence_ids: string[] }[] }[];
  impediments: { summary: string; severity: string; status: 'NEW' | 'OPEN' | 'RESOLVED'; age_label: string; evidence_ids: string[] }[];
  risks: { type: string; text: string; evidence_ids: string[] }[];
  participation: { responded: string[]; pending: string[] };
  people: { name: string; checkin_id: string; confirmed_at: string; done: string; planned: string; blocker: string }[];
  evidence_labels: Record<string, string>;
}
export interface ReportVersion { id: number; version: number; generated_at: string; responded: number; incomplete_review: boolean; }
export interface Report extends ReportVersion {
  content: ReportContent; feedback: Record<string, 'useful' | 'not_useful'>; prompt_version: string;
}

export interface TeamDetail {
  id: string; name: string; timezone: string; cutoff_time: string; base_questions: string[];
  members: { id: number; name: string; email: string; role: Role }[];
}

// Eventos do stream do agente (backend/app/agent_runner.py)
export type AgentEvent =
  | { type: 'agent'; text: string }
  | { type: 'review'; interrupt_id: string; invocation_id: string; draft: CheckinDraft }
  | { type: 'saved'; text: string; checkin_id: string }
  | { type: 'discarded'; text: string }
  | { type: 'step'; step: number }
  | { type: 'done'; report_id: number }
  | { type: 'error'; text: string };
