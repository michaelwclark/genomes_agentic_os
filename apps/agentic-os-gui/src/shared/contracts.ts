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

export interface GuiSnapshot {
  schema_version: string;
  generated_at: string;
  root: string;
  navigation: { domains: DomainScope[] };
  conversations: ConversationSummary[];
  diagnostics: Diagnostic[];
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
  snapshot: "aos:snapshot",
  transcript: "aos:transcript",
  setPinned: "aos:set-pinned",
  sendTurn: "aos:send-turn",
  cancelTurn: "aos:cancel-turn",
  openExternal: "aos:open-external",
  snapshotChanged: "aos:snapshot-changed",
  streamEvent: "aos:stream-event",
} as const;

export interface AgenticOSApi {
  getSnapshot(): Promise<GuiSnapshot>;
  getTranscript(conversationId: string): Promise<ConversationTranscript>;
  setPinned(conversationId: string, pinned: boolean): Promise<OperatorState>;
  sendTurn(request: SendTurnRequest): Promise<SendTurnResult>;
  cancelTurn(leaseId: string): Promise<boolean>;
  openExternal(url: string): Promise<boolean>;
  onSnapshotChanged(listener: (snapshot: GuiSnapshot) => void): () => void;
  onStreamEvent(listener: (event: StreamEvent) => void): () => void;
}
