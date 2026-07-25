import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import type {
  ConversationSummary,
  ConversationTranscript,
  GuiSnapshot,
  Harness,
  OperatorState,
} from "../shared/contracts";
import { fixtureSnapshot, fixtureTranscripts } from "../shared/fixtures";

const execFileAsync = promisify(execFile);
const MAX_OUTPUT_BYTES = 32 * 1024 * 1024;

export function resolveAgenticOsCli(
  configured = process.env.AGENTIC_OS_CLI,
  home = homedir(),
  exists: (path: string) => boolean = existsSync,
): string {
  if (configured) return configured;
  const candidates = [
    join(home, "Library", "Application Support", "AgenticOSGui", "runtime", "bin", "agentic-os"),
    join(home, ".local", "bin", "agentic-os"),
    "/opt/homebrew/bin/agentic-os",
    "/usr/local/bin/agentic-os",
  ];
  return candidates.find(exists) || "agentic-os";
}

function parseJson<T>(stdout: string, operation: string): T {
  try {
    return JSON.parse(stdout) as T;
  } catch (error) {
    throw new Error(`${operation} returned invalid JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
}

export function normalizeSnapshot(value: GuiSnapshot, root: string, state: OperatorState): GuiSnapshot {
  const native = value && typeof value === "object" ? value : ({} as GuiSnapshot);
  const domains = Array.isArray(native.navigation?.domains) ? native.navigation.domains : [];
  const pins = new Set(state.pinnedConversationIds);
  const conversations = Array.isArray(native.conversations) ? native.conversations : [];
  const generatedAt = native.generated_at || new Date().toISOString();
  const fallbackRuntime = {
    status: "unavailable" as const, queue_mode: "unknown", queue_depth: 0, running: 0,
    failed: 0, recent_failures: 0, dead_letter: 0, active_workers: 0, unhealthy_workers: 0,
    registered_workers: 0, historical_worker_records: 0,
    retrying: 0, delayed_retries: 0, oldest_wait_seconds: 0,
    reserved_interactive_slots: 1,
    max_interactive_running: 1,
    queues: [], worker_pools: [], workers: [], running_tasks: [], tasks: [], task_count: 0,
    task_sample_count: 0, task_sample_limit: 200,
    completed: 0,
    control_plane: { transport: "unknown" as const, role: "unknown" as const },
    healing: { status: "unknown" as const, repairs: 0, failures: 0 },
    alarms: [],
    recent_run_reports: [],
    captured_at: generatedAt,
  };
  const runtime = native.runtime ? {
    ...native.runtime,
    queues: (Array.isArray(native.runtime.queues) ? native.runtime.queues : []).map((queue) => {
      const statuses = queue.statuses && typeof queue.statuses === "object" ? queue.statuses : {};
      return {
        ...queue,
        statuses,
        total: Number(queue.total || 0),
        depth: Number(queue.depth ?? Number(statuses.queued || 0) + Number(statuses["approval-needed"] || 0)),
        running: Number(queue.running ?? statuses.running ?? 0),
        failed: Number(queue.failed ?? statuses.failed ?? 0),
        dead_letter: Number(queue.dead_letter ?? statuses["dead-letter"] ?? 0),
        retrying: Number(queue.retrying ?? 0),
        delayed_retries: Number(queue.delayed_retries ?? 0),
      };
    }),
    worker_pools: Array.isArray(native.runtime.worker_pools) ? native.runtime.worker_pools : [],
    workers: Array.isArray(native.runtime.workers) ? native.runtime.workers : [],
    running_tasks: Array.isArray(native.runtime.running_tasks)
      ? native.runtime.running_tasks
      : (Array.isArray(native.runtime.tasks) ? native.runtime.tasks.filter((task) => task.status === "running") : []),
    tasks: Array.isArray(native.runtime.tasks) ? native.runtime.tasks : [],
    task_count: Number.isInteger(native.runtime.task_count) ? native.runtime.task_count : 0,
    task_sample_count: Number.isInteger(native.runtime.task_sample_count) ? native.runtime.task_sample_count : (Array.isArray(native.runtime.tasks) ? native.runtime.tasks.length : 0),
    task_sample_limit: Number.isInteger(native.runtime.task_sample_limit) ? native.runtime.task_sample_limit : 200,
    captured_at: native.runtime.captured_at || generatedAt,
    max_interactive_running: Number.isInteger(native.runtime.max_interactive_running) ? native.runtime.max_interactive_running : 1,
    retrying: Number(native.runtime.retrying || 0),
    delayed_retries: Number(native.runtime.delayed_retries || 0),
    oldest_wait_seconds: Number(native.runtime.oldest_wait_seconds || 0),
    recent_failures: Number(native.runtime.recent_failures || 0),
    registered_workers: Number(native.runtime.registered_workers || 0),
    historical_worker_records: Number(native.runtime.historical_worker_records || 0),
    completed: Number(native.runtime.completed || 0),
    effects: native.runtime.effects ? {
      pending: Number(native.runtime.effects.pending || 0),
      delivering: Number(native.runtime.effects.delivering || 0),
      delivered: Number(native.runtime.effects.delivered || 0),
      failed: Number(native.runtime.effects.failed || 0),
      dead_letter: Number(native.runtime.effects.dead_letter || 0),
    } : undefined,
    control_plane: native.runtime.control_plane ?? fallbackRuntime.control_plane,
    config: native.runtime.config ? {
      ...native.runtime.config,
      drifted: Boolean(native.runtime.config.drifted),
    } : undefined,
    healing: native.runtime.healing ? {
      ...native.runtime.healing,
      repairs: Number(native.runtime.healing.repairs || 0),
      failures: Number(native.runtime.healing.failures || 0),
    } : fallbackRuntime.healing,
    alarms: Array.isArray(native.runtime.alarms) ? native.runtime.alarms : [],
    recent_run_reports: Array.isArray(native.runtime.recent_run_reports) ? native.runtime.recent_run_reports : [],
  } : fallbackRuntime;
  const launchedByOwnedId = new Map(
    Object.values(state.launchedSessions).map((session) => [`${session.harness}:${session.sessionId}`, session]),
  );
  return {
    schema_version: native.schema_version || "agentic-os-gui/v1",
    generated_at: generatedAt,
    root: native.root || root,
    navigation: { domains },
    runtime,
    conversations: conversations.filter((conversation) => !launchedByOwnedId.has(`${conversation.harness}:${conversation.id}`)).map((conversation) => {
      const override = state.routeOverrides[conversation.id];
      const overlayPinned = pins.has(`${conversation.harness}:${conversation.id}`);
      const launched = state.launchedSessions[`${conversation.harness}:${conversation.id}`];
      const owned = launched
        ? conversations.find((candidate) => candidate.harness === launched.harness && candidate.id === launched.sessionId)
        : undefined;
      const updatedAt = [conversation.updated_at, owned?.updated_at, launched?.updatedAt]
        .filter((candidate): candidate is string => Boolean(candidate))
        .sort()
        .at(-1);
      return {
        ...conversation,
        title: conversation.title?.trim() || `${conversation.harness === "claude" ? "Claude" : "Codex"} task`,
        provider: conversation.provider || providerFor(conversation),
        status: conversation.status || "unknown",
        updated_at: updatedAt || conversation.created_at || native.generated_at,
        domain: override?.domain ?? conversation.domain,
        project: override?.project ?? conversation.project,
        pinned: Boolean(conversation.pinned || overlayPinned),
        pin_source:
          conversation.pinned && overlayPinned ? "both" : overlayPinned ? "agentic-os" : conversation.pinned ? "native" : undefined,
        can_continue: launched ? true : conversation.can_continue,
        metadata: launched
          ? { ...conversation.metadata, gui_owned_session_id: launched.sessionId, continuation_source_id: launched.sourceResumeId }
          : conversation.metadata,
      };
    }),
    diagnostics: Array.isArray(native.diagnostics) ? native.diagnostics : [],
  };
}

function providerFor(conversation: ConversationSummary): "openai" | "anthropic" | "unknown" {
  if (conversation.harness === "codex") return "openai";
  if (conversation.harness === "claude") return "anthropic";
  return "unknown";
}

export class AosBridge {
  private snapshotCache?: GuiSnapshot;
  private snapshotInFlight?: Promise<GuiSnapshot>;
  private snapshotGeneration = 0;

  constructor(
    private readonly root: string,
    private readonly readOperatorState: () => Promise<OperatorState>,
    private readonly fixtureMode = process.env.AOS_GUI_FIXTURE === "1",
    private readonly executable = resolveAgenticOsCli(),
  ) {}

  async snapshot(force = false): Promise<GuiSnapshot> {
    if (!force && this.snapshotCache) return this.snapshotCache;
    if (this.snapshotInFlight) return this.snapshotInFlight;
    const generation = this.snapshotGeneration;
    const load = (async () => {
      const state = await this.readOperatorState();
      if (this.fixtureMode) return normalizeSnapshot(structuredClone(fixtureSnapshot), this.root, state);
      const { stdout } = await execFileAsync(
        this.executable,
        ["gui", "snapshot", "--root", this.root, "--json"],
        { encoding: "utf8", maxBuffer: MAX_OUTPUT_BYTES, timeout: 30_000 },
      );
      return normalizeSnapshot(parseJson<GuiSnapshot>(stdout, "gui snapshot"), this.root, state);
    })();
    const pending = load.then(
      async (snapshot) => {
        if (generation !== this.snapshotGeneration) {
          if (this.snapshotInFlight === pending) this.snapshotInFlight = undefined;
          return this.snapshot(true);
        }
        this.snapshotCache = snapshot;
        return snapshot;
      },
      async (error: unknown) => {
        if (generation !== this.snapshotGeneration) {
          if (this.snapshotInFlight === pending) this.snapshotInFlight = undefined;
          return this.snapshot(true);
        }
        throw error;
      },
    );
    this.snapshotInFlight = pending;
    try {
      return await pending;
    } finally {
      if (this.snapshotInFlight === pending) this.snapshotInFlight = undefined;
    }
  }

  invalidate(): void {
    this.snapshotCache = undefined;
    this.snapshotGeneration += 1;
  }

  async conversation(conversationId: string): Promise<ConversationSummary | undefined> {
    return (await this.snapshot()).conversations.find((item) => item.id === conversationId);
  }

  async transcript(conversationId: string): Promise<ConversationTranscript> {
    const conversation = await this.conversation(conversationId);
    if (!conversation) throw new Error("conversation is not present in the current Agentic OS snapshot");
    if (this.fixtureMode) {
      return structuredClone(
        fixtureTranscripts[conversationId] ?? { conversation_id: conversationId, messages: [], diagnostics: [] },
      );
    }
    const provider: Harness = conversation.harness;
    if (provider !== "codex" && provider !== "claude") throw new Error("conversation provider is unsupported");
    const state = await this.readOperatorState();
    const launchedSession = state.launchedSessions[`${provider}:${conversationId}`];
    const transcriptConversationId = launchedSession?.sessionId ?? conversationId;
    const { stdout } = await execFileAsync(
      this.executable,
      [
        "gui",
        "transcript",
        "--root",
        this.root,
        "--provider",
        provider,
        "--conversation-id",
        transcriptConversationId,
        "--json",
      ],
      { encoding: "utf8", maxBuffer: MAX_OUTPUT_BYTES, timeout: 30_000 },
    );
    const transcript = parseJson<ConversationTranscript>(stdout, "gui transcript");
    return {
      conversation_id: conversationId,
      messages: Array.isArray(transcript.messages) ? transcript.messages : [],
      truncated: Boolean(transcript.truncated),
      continuation: transcript.continuation,
      diagnostics: Array.isArray(transcript.diagnostics) ? transcript.diagnostics : [],
    };
  }
}
