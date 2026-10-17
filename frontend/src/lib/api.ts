export type JobStatus = 'pending' | 'running' | 'waiting_user' | 'waiting_candidate_confirmation' | 'completed' | 'partial' | 'failed' | 'cancelled';
export type AnalysisMode = 'standard' | 'deep';

export interface User { id: string; email: string; created_at: string; is_active: boolean; }
export interface JobEvent { event_type: string; message: string; progress: number; level: 'info' | 'warning' | 'error'; created_at: string; }
export interface ClarificationOption { id: string; label: string; description: string; }
export interface ClarificationRequest { request_id: string; round: number; question: string; options: ClarificationOption[]; allow_custom: boolean; status: 'pending' | 'answered'; selected_option_id?: string | null; custom_answer?: string | null; answered_at?: string | null; }
export interface ClarificationState { job_id: string; max_rounds: number; current: ClarificationRequest | null; history: ClarificationRequest[]; }
export interface Job { id: string; query: string; platforms: string[]; analysis_mode: AnalysisMode; status: JobStatus; progress: number; clarification_round: number; execution_version: number; revision_of_job_id?: string | null; can_retry: boolean; can_revise: boolean; can_confirm_candidates: boolean; is_stopping?: boolean; topic_spec?: Record<string, unknown> | null; interaction_usage?: Record<string, unknown>; error_code?: string | null; error_message?: string | null; report_id?: string | null; created_at: string; started_at?: string | null; completed_at?: string | null; events?: JobEvent[]; }
export type CandidateDecision = 'undecided' | 'confirmed' | 'excluded' | 'uncertain';
export interface CandidateEvidenceLink { evidence_id: string; title: string; source_url: string; }
export interface CandidateAccount { candidate_id: string; platform: 'bilibili'; platform_account_id: string; display_name: string; profile_url: string; source_evidence_ids: string[]; matched_video_count: number; sample_titles: string[]; evidence_links: CandidateEvidenceLink[]; why_surfaced: string[]; identity_confidence: 'high'; decision: CandidateDecision; reason: string; }
export interface CandidateTopicSummary { topic: string; target_content: string[]; competitor_definition: string; time_window_days?: number | null; assumptions: string[]; }
export interface CandidateSnapshot { snapshot_id: string; snapshot_version: string; topic_spec: CandidateTopicSummary; candidates: CandidateAccount[]; max_candidates: number; can_submit: boolean; snapshot_hash: string; }
export interface Claim { claim: string; claim_type: 'observation' | 'inference' | 'recommendation'; evidence_ids: string[]; confidence: number; }
export interface EvidenceItem { evidence_id: string; tool: string; source_type: string; title: string; source_url?: string | null; platform: string; fetched_at: string; raw_data?: Record<string, unknown>; summary?: string | null; data_fields?: Record<string, unknown>; transcript_segment?: Record<string, unknown> | null; }
export interface Report { id: string; job_id: string; title: string; content: string; structured_claims: Claim[]; status: JobStatus; model_info: Record<string, unknown>; evidence: EvidenceItem[]; usage?: UsageRecord | null; created_at: string; updated_at: string; }
export interface UsageRecord { input_tokens: number; output_tokens: number; estimated_cost: number; asr_seconds: number; }
export interface UsageSummary { jobs_used: number; jobs_limit: number; input_tokens: number; output_tokens: number; estimated_cost: number; asr_seconds: number; }
export interface Capability { name: string; enabled: boolean; availability: string; supported_platforms: string[]; }
export interface ApiErrorShape { error_code: string; message: string; }

export class ApiError extends Error { constructor(public status: number, public code: string, message: string) { super(message); } }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, credentials: 'include', headers: { ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers } });
  if (!response.ok) { let payload: Partial<ApiErrorShape> = {}; try { payload = await response.json(); } catch {} throw new ApiError(response.status, payload.error_code || 'REQUEST_FAILED', payload.message || '请求失败，请稍后重试。'); }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export const register = (email: string, password: string) => request<User>('/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) });
export const login = (email: string, password: string) => request<User>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
export const logout = () => request<void>('/auth/logout', { method: 'POST' });
export const getCurrentUser = () => request<User>('/auth/me');
export const createJob = (data: { query: string; analysis_mode: AnalysisMode; idempotency_key: string }) => request<Job>('/jobs', { method: 'POST', body: JSON.stringify({ ...data, platforms: ['bilibili'] }) });
export const listJobs = (params = '') => request<{ items: Job[]; total: number }>(`/jobs${params}`);
export const getJob = (id: string, signal?: AbortSignal) => request<Job>(`/jobs/${id}`, { signal });
export const cancelJob = (id: string) => request<Job>(`/jobs/${id}/cancel`, { method: 'POST' });
export const retryJob = (id: string) => request<Job>(`/jobs/${id}/retry`, { method: 'POST' });
export const reviseJob = (id: string, data: { query: string; idempotency_key: string }) => request<Job>(`/jobs/${id}/revisions`, { method: 'POST', body: JSON.stringify(data) });
export const getJobEvents = (id: string, signal?: AbortSignal) => request<{ items: JobEvent[] }>(`/jobs/${id}/events`, { signal });
export const getJobClarification = (id: string, signal?: AbortSignal) => request<ClarificationState>(`/jobs/${id}/clarification`, { signal });
export const answerJobClarification = (id: string, data: { request_id: string; selected_option_id?: string; custom_answer?: string }) => request<Job>(`/jobs/${id}/clarification`, { method: 'POST', body: JSON.stringify(data) });
export const getJobCandidates = (id: string, signal?: AbortSignal) => request<CandidateSnapshot>(`/jobs/${id}/candidates`, { signal });
export const submitCandidateDecisions = (id: string, data: { request_id: string; snapshot_id: string; decisions: { candidate_id: string; decision: Exclude<CandidateDecision, 'undecided'>; reason?: string }[] }) => request<Job>(`/jobs/${id}/candidates/decisions`, { method: 'POST', body: JSON.stringify(data) });
export const getReport = (id: string) => request<Report>(`/reports/${id}`);
export const deleteJob = (id: string) => request<void>(`/jobs/${id}`, { method: 'DELETE' });
export const getUsage = () => request<UsageSummary>('/usage');
export const getCapabilities = () => request<{ items: Capability[]; platforms: string[] }>('/capabilities');
export const createShareLink = (reportId: string, expiresInDays: number) => request<{ token: string; expires_at: string }>(`/reports/${reportId}/shares`, { method: 'POST', body: JSON.stringify({ expires_in_days: expiresInDays }) });
export const getSharedReport = (token: string) => request<Report>(`/shares/${token}`);
export const createFeedback = (reportId: string, data: { rating: number; useful: boolean; reason: string; comment: string; adopted: boolean | null }) => request<void>(`/reports/${reportId}/feedback`, { method: 'POST', body: JSON.stringify(data) });

export function readableError(error: unknown) { return error instanceof ApiError ? error.message : '网络异常，请检查连接后重试。'; }
