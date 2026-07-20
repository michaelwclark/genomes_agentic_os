export type Harness = "codex" | "claude" | "unknown";
export type Provider = "openai" | "anthropic" | "unknown";
export type ModelTier = "economy" | "balanced" | "frontier" | "frontier_max" | "human_gate" | "unknown";
export type ReasoningEffort = "low" | "medium" | "high" | "xhigh" | "max" | "ultra" | "unknown";

export interface ProjectScope {
  id: string;
  name: string;
  domain: string;
  status?: string;
  conversation_count?: number;
}

export interface DomainScope {
  id: string;
  name: string;
  projects: ProjectScope[];
}

export interface LinkedPullRequest {
  number?: string | number;
  url: string;
  repo?: string;
  status?: string;
}

export interface LinkedIssue {
  key: string;
  url: string;
  title?: string;
  status?: string;
}

export interface LinkedAsset {
  label: string;
  path: string;
  kind?: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  harness: Harness;
  provider: Provider;
  model?: string;
  model_tier?: ModelTier;
  reasoning_effort?: ReasoningEffort;
  status: string;
  updated_at: string;
  created_at?: string;
  domain?: string;
  project?: string;
  work_item?: string;
  cwd?: string;
  pinned?: boolean;
  pin_source?: "native" | "agentic-os" | "both";
  imported?: boolean;
  can_continue?: boolean;
  continuation_note?: string;
  continuation?: { session_id?: string; cli_session_id?: string; [key: string]: unknown };
  /** Trusted native CLI session identifier supplied by the Agentic OS snapshot. */
  cli_session_id?: string;
  jira_keys?: string[];
  jira_issues?: LinkedIssue[];
  linear_issues?: LinkedIssue[];
  pull_requests?: LinkedPullRequest[];
  slack_threads?: string[];
  assets?: LinkedAsset[];
  git?: { branch?: string; origin?: string };
  source?: string;
  summary?: string;
  metadata?: Record<string, unknown>;
}

export interface TranscriptMessage {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  created_at?: string;
  status?: string;
}

export interface ConversationTranscript {
  conversation_id: string;
  messages: TranscriptMessage[];
  truncated?: boolean;
  continuation?: {
    supported: boolean;
    mode?: string;
    note?: string;
    fallback_command?: string;
  };
  diagnostics?: Diagnostic[];
}

export interface Diagnostic {
  severity: "info" | "warning" | "error";
  message: string;
  source?: string;
}

export interface RuntimeQueue {
  queue_name: string;
  statuses: Record<string, number>;
  total: number;
  depth: number;
  running: number;
  failed: number;
  dead_letter: number;
  retrying?: number;
  delayed_retries?: number;
  max_concurrency?: number;
  max_queued?: number;
  enabled?: boolean;
}

export interface RuntimeWorkerPool {
  name: string;
  queue_name: string;
  provider: string;
  max_workers: number;
  max_concurrency: number;
  worker_count: number;
  live_workers: number;
  active_tasks: number;
  unhealthy_workers: number;
}

export interface RuntimeWorker {
  id: string;
  pool_name: string;
  queue_name: string;
  provider: string;
  status: string;
  capacity: number;
  active_tasks: number;
  heartbeat_at?: string;
  lease_until?: string;
  updated_at?: string;
}

export interface RuntimeTask {
  id: string;
  display_name?: string;
  kind?: string;
  status: string;
  queue_name: string;
  worker_pool: string;
  priority?: number;
  execution_target?: string;
  attempts?: number;
  created_at?: string;
  updated_at?: string;
  due_at?: string;
  started_at?: string;
  finished_at?: string;
  lease_owner?: string;
  lease_until?: string;
}

export interface LongRunningRun {
  id: string;
  kind?: string;
  label: string;
  status: string;
  phase?: string;
  created_at?: string;
  updated_at?: string;
  last_progress_at?: string;
  run_dir?: string;
  terminal_reason?: string;
  items_completed?: number;
  items_total?: number;
  files_completed?: number;
  files_total?: number;
  bytes_completed?: number;
  bytes_total?: number;
  output_bytes?: number;
}

export interface RuntimeHealth {
  status: "healthy" | "degraded" | "critical" | "unavailable";
  queue_mode: string;
  queue_depth: number;
  running: number;
  failed: number;
  recent_failures: number;
  dead_letter: number;
  active_workers: number;
  unhealthy_workers: number;
  registered_workers: number;
  historical_worker_records: number;
  retrying: number;
  delayed_retries: number;
  oldest_wait_seconds: number;
  stale_queued?: number;
  expired_running_leases?: number;
  reserved_interactive_slots: number;
  max_interactive_running: number;
  queues: RuntimeQueue[];
  worker_pools: RuntimeWorkerPool[];
  workers: RuntimeWorker[];
  running_tasks: RuntimeTask[];
  tasks: RuntimeTask[];
  task_count: number;
  task_sample_count: number;
  task_sample_limit: number;
  long_running_runs?: LongRunningRun[];
  long_running_active?: number;
  long_running_attention?: number;
  captured_at: string;
  reason?: string;
}

export interface GuiSnapshot {
  schema_version: string;
  generated_at: string;
  root: string;
  navigation: { domains: DomainScope[] };
  runtime: RuntimeHealth;
  conversations: ConversationSummary[];
  diagnostics: Diagnostic[];
}

export interface UiConfig {
  displayName: string;
  operatorLabel: string;
}

export interface OperatorState {
  schemaVersion: 1;
  pinnedConversationIds: string[];
  routeOverrides: Record<string, { domain?: string; project?: string }>;
  lastScope?: { domain?: string; project?: string };
  launchedSessions: Record<string, LaunchedSession>;
}

export interface LaunchedSession {
  harness: Harness;
  /** GUI-owned session id. For Claude this is created with --fork-session. */
  sessionId: string;
  sourceConversationId: string;
  sourceResumeId: string;
  createdAt: string;
  updatedAt: string;
  model?: string;
  reasoningEffort?: ReasoningEffort;
}

export interface ConversationFilter {
  domain?: string;
  project?: string;
  query?: string;
}

export interface SendTurnRequest {
  conversationId: string;
  harness: Harness;
  prompt: string;
  cwd?: string;
  imported?: boolean;
}

export interface StreamEvent {
  conversationId: string;
  kind: "started" | "delta" | "message" | "tool" | "completed" | "error";
  content?: string;
  rawType?: string;
  fallbackCommand?: string;
}

export interface SendTurnResult {
  accepted: boolean;
  leaseId?: string;
  message?: string;
  fallbackCommand?: string;
}

export const IPC = {
  uiConfig: "aos:ui-config",
  snapshot: "aos:snapshot",
  transcript: "aos:transcript",
  setPinned: "aos:set-pinned",
  sendTurn: "aos:send-turn",
  cancelTurn: "aos:cancel-turn",
  openExternal: "aos:open-external",
  openLocalTarget: "aos:open-local-target",
  snapshotChanged: "aos:snapshot-changed",
  streamEvent: "aos:stream-event",
} as const;

export interface AgenticOSApi {
  getUiConfig(): Promise<UiConfig>;
  getSnapshot(): Promise<GuiSnapshot>;
  getTranscript(conversationId: string): Promise<ConversationTranscript>;
  setPinned(conversationId: string, pinned: boolean): Promise<OperatorState>;
  sendTurn(request: SendTurnRequest): Promise<SendTurnResult>;
  cancelTurn(leaseId: string): Promise<boolean>;
  openExternal(url: string): Promise<boolean>;
  openLocalTarget(
    conversationId: string,
    target: "work-item",
    action: "vscode" | "finder",
  ): Promise<boolean>;
  onSnapshotChanged(listener: (snapshot: GuiSnapshot) => void): () => void;
  onStreamEvent(listener: (event: StreamEvent) => void): () => void;
}
