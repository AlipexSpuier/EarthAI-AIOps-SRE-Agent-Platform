export type ControlLevel = 'observe' | 'approve' | 'autonomous';
export type SpaceModule = 'personal' | 'team';
export type Theme = 'light' | 'dark' | 'system';
export interface ChatPreferences {
  server_id: string | null; provider_id: string | null; model: string; agent_id: string | null;
  project_id: string | null; control_level: ControlLevel;
}
export interface User { id: string; email: string; name: string; avatar: string; theme: Theme; control_level: ControlLevel; allowed_control_levels?: ControlLevel[]; space_modules?: SpaceModule[]; team_invites_blocked?: boolean; chat_preferences?: ChatPreferences; role?: 'user' | 'admin'; disabled?: boolean; must_change_password?: boolean }
export interface ResourcePermissions { read_only?: boolean; default_template_id?: string }
export type RunStatus = 'queued' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
export interface Conversation {
  id: string; title: string; agent_id?: string | null; project_id?: string | null; server_id?: string | null;
  provider_id?: string | null; model?: string | null; control_level: ControlLevel; created_at: string; updated_at: string;
}
export interface Message { id: string; role: 'user' | 'assistant' | 'system' | 'tool'; content: string; created_at: string; run_id?: string | null }
export interface Run {
  id: string; conversation_id: string; status: RunStatus; goal: string; server_id?: string | null; provider_id?: string | null;
  model?: string | null; control_level: ControlLevel; summary?: string | null; error?: string | null;
  created_at: string; updated_at: string; step_count: number;
}
export type RunEventType = 'status' | 'plan' | 'model_start' | 'assistant_delta' | 'assistant' | 'model_end' | 'notice' | 'tool_start' | 'tool_execution' | 'tool_output' | 'tool_result' | 'approval' | 'error' | 'done';
export interface ModelEventData extends Record<string, unknown> { message_id: string; turn: number }
export interface ModelStartData extends ModelEventData { model: string }
export interface AssistantDeltaData extends ModelEventData { delta: string; reset?: boolean }
export interface ModelEndData extends ModelEventData { finish_reason?: string; streamed?: boolean; duration_ms?: number; usage?: Record<string, unknown> }
export interface RunEvent {
  id: number; run_id: string; type: RunEventType;
  data: Record<string, unknown>; created_at: string;
}
export interface Approval {
  id: string; run_id: string; tool_name: string; tool_call_id?: string; arguments: unknown; risk: string; status: string; created_at: string;
}
export interface RunDetail { run: Run; events: RunEvent[]; approvals: Approval[] }
export interface ConversationDetail { conversation: Conversation; messages: Message[]; runs: Run[] }
export interface Provider extends ResourcePermissions { id: string; name: string; base_url: string; has_api_key: boolean; models: string[]; default_model: string; enabled: boolean; model_sync?: { status: 'ok' | 'empty' | 'error' | 'stale'; message: string; count?: number; synced_at?: string | null } }
export interface Server extends ResourcePermissions {
  id: string; name: string; kind: 'ssh' | 'kubernetes'; host: string; port: number; username: string;
  auth_type: 'password' | 'key'; fingerprint: string; trust_on_first_use?: boolean; fingerprint_trusted_at?: string; has_credentials: boolean; description: string;
  tags: string[]; status: 'unknown' | 'online' | 'offline'; last_checked_at?: string | null;
}
export interface Agent extends ResourcePermissions {
  kind?: 'local' | 'remote'; url?: string; sort_order?: number; usage_count?: number;
  id: string; name: string; description: string; system_prompt: string; icon: string; color: string;
  skill_ids: string[]; knowledge_ids: string[]; provider_id?: string | null; model?: string | null; control_level: ControlLevel;
}
export interface Project extends ResourcePermissions { id: string; name: string; description: string; color: string; server_ids: string[]; skill_ids?: string[]; knowledge_ids: string[]; status: 'active' | 'archived' }
export interface Skill extends ResourcePermissions { id: string; name: string; description: string; content: string; enabled: boolean; usage_count?: number }
export interface Knowledge extends ResourcePermissions { id: string; name: string; description: string; document_count: number; chunk_count: number; usage_count?: number }
export interface KnowledgeDocument { id: string; name: string; size: number; chunk_count: number; created_at: string }
export interface SearchResult { id: string; knowledge_id: string; document_name: string; content: string; score: number }
export interface PersonalFile { id: string; name: string; size: number; mime: string; created_at: string }
export interface Schedule extends ResourcePermissions {
  id: string; name: string; prompt: string; server_id?: string | null; provider_id?: string | null; model?: string | null;
  agent_id?: string | null; control_level: ControlLevel; cron: string; timezone: string; enabled: boolean;
  next_run_at?: string | null; last_run_at?: string | null; last_run_id?: string | null;
}
export interface Alert { id: string; title: string; severity: 'critical' | 'warning' | 'info'; status: 'open' | 'resolved'; source: string; description: string; server_id?: string | null; run_id?: string | null; created_at: string }
export interface Audit { id: string; action: string; resource: string; detail: unknown; created_at: string }
export interface Overview {
  counts: Record<'servers' | 'conversations' | 'runs' | 'files' | 'knowledge' | 'skills' | 'projects' | 'schedules' | 'alerts' | 'providers', number>;
  active_runs: Run[]; recent_runs: Run[]; alerts: Alert[]; daily_runs: { date: string; count: number }[];
  recent_audit: Audit[]; health: { database: string; status: string; version: string };
}
export interface TestResult { ok: boolean; message: string; models?: string[]; details?: unknown }
export interface RunLaunch { run_id: string; conversation_id: string }
export interface Catalog { servers: Server[]; providers: Provider[]; agents: Agent[]; projects: Project[]; knowledge: Knowledge[]; skills: Skill[] }
