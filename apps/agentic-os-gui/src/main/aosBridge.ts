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
  const launchedByOwnedId = new Map(
    Object.values(state.launchedSessions).map((session) => [`${session.harness}:${session.sessionId}`, session]),
  );
  return {
    schema_version: native.schema_version || "agentic-os-gui/v1",
    generated_at: native.generated_at || new Date().toISOString(),
    root: native.root || root,
    navigation: { domains },
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

  constructor(
    private readonly root: string,
    private readonly readOperatorState: () => Promise<OperatorState>,
    private readonly fixtureMode = process.env.AOS_GUI_FIXTURE === "1",
    private readonly executable = resolveAgenticOsCli(),
  ) {}

  async snapshot(force = false): Promise<GuiSnapshot> {
    if (!force && this.snapshotCache) return this.snapshotCache;
    const state = await this.readOperatorState();
    if (this.fixtureMode) {
      this.snapshotCache = normalizeSnapshot(structuredClone(fixtureSnapshot), this.root, state);
      return this.snapshotCache;
    }
    const { stdout } = await execFileAsync(
      this.executable,
      ["gui", "snapshot", "--root", this.root, "--json"],
      { encoding: "utf8", maxBuffer: MAX_OUTPUT_BYTES, timeout: 30_000 },
    );
    this.snapshotCache = normalizeSnapshot(parseJson<GuiSnapshot>(stdout, "gui snapshot"), this.root, state);
    return this.snapshotCache;
  }

  invalidate(): void {
    this.snapshotCache = undefined;
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
