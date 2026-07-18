import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { SendTurnRequest, SendTurnResult, StreamEvent } from "../shared/contracts";

export interface BrokerTurnRequest extends SendTurnRequest {
  /** Trusted by main from the cached snapshot/operator state; never renderer input. */
  resumeId: string;
  forkSession?: boolean;
  newSessionId?: string;
}

interface Lease {
  id: string;
  key: string;
  child: ChildProcessWithoutNullStreams;
  stopping: boolean;
  killTimer?: NodeJS.Timeout;
  waiters: Array<() => void>;
}

type Emit = (event: StreamEvent) => void;
type SpawnProcess = typeof spawn;

export interface BrokerCommand {
  executable: string;
  args: string[];
  continuationMode: "resume";
}

export function resolveProviderCli(
  provider: "codex" | "claude",
  configured: string | undefined,
  home = homedir(),
  exists: (path: string) => boolean = existsSync,
): string {
  if (configured) return configured;
  const candidates = provider === "codex"
    ? [
        join(home, ".local", "bin", "codex"),
        "/Applications/ChatGPT.app/Contents/Resources/codex",
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
      ]
    : [
        join(home, ".local", "bin", "claude"),
        join(home, ".claude", "local", "claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
      ];
  return candidates.find(exists) || provider;
}

export function brokerCommand(request: BrokerTurnRequest, env: NodeJS.ProcessEnv = process.env): BrokerCommand {
  if (request.harness === "codex") {
    return {
      executable: resolveProviderCli("codex", env.CODEX_BIN),
      args: ["exec", "resume", request.resumeId, "-", "--json", "--skip-git-repo-check"],
      continuationMode: "resume",
    };
  }
  const args = [
    "--print",
    "--resume",
    request.resumeId,
    "--input-format",
    "text",
    "--output-format",
    "stream-json",
    "--include-partial-messages",
    "--verbose",
  ];
  if (request.forkSession) {
    if (!request.newSessionId) throw new Error("forked Claude sessions require a new session id");
    args.push("--fork-session", "--session-id", request.newSessionId);
  }
  return {
    executable: resolveProviderCli("claude", env.CLAUDE_BIN),
    args,
    continuationMode: "resume",
  };
}

function fallbackFor(request: BrokerTurnRequest): string {
  if (request.harness === "codex") return `codex resume ${request.resumeId}`;
  if (request.forkSession && request.newSessionId) {
    return `claude --resume ${request.resumeId} --fork-session --session-id ${request.newSessionId}`;
  }
  return `claude --resume ${request.resumeId}`;
}

function safeProviderError(executable: string, stderr: string, code: number | null): string {
  const normalized = stderr.replace(/\s+/g, " ").trim();
  if (/credit balance is too low/i.test(normalized)) return `${executable} credit balance is too low.`;
  if (/requires? --verbose/i.test(normalized)) return `${executable} requires --verbose for stream JSON output.`;
  if (/authentication|unauthorized|not logged in/i.test(normalized)) return `${executable} authentication is unavailable.`;
  return `${executable} exited with status ${code ?? "unknown"}; use the guarded native-harness fallback.`;
}

export function textualContent(value: unknown): string | undefined {
  if (!value || typeof value !== "object") return undefined;
  const row = value as Record<string, unknown>;
  for (const key of ["delta", "text"]) {
    const candidate = row[key];
    if (typeof candidate === "string") return candidate.slice(0, 100_000);
  }
  const message = row.message;
  if (message && typeof message === "object") {
    const content = (message as Record<string, unknown>).content;
    if (typeof content === "string") return content.slice(0, 100_000);
    if (Array.isArray(content)) {
      const parts = content
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
        .filter((item) => item.type === "text" && typeof item.text === "string")
        .map((item) => String(item.text));
      if (parts.length) return parts.join("\n").slice(0, 100_000);
    }
  }
  const item = row.item;
  if (item && typeof item === "object") {
    const itemRow = item as Record<string, unknown>;
    if (itemRow.type === "agent_message" && typeof itemRow.text === "string") {
      return itemRow.text.slice(0, 100_000);
    }
  }
  const delta = row.delta;
  if (delta && typeof delta === "object" && typeof (delta as Record<string, unknown>).text === "string") {
    return String((delta as Record<string, unknown>).text).slice(0, 100_000);
  }
  const event = row.event;
  if (event && typeof event === "object") return textualContent(event);
  return undefined;
}

function safeEventType(value: unknown): string | undefined {
  return typeof value === "string" && /^[A-Za-z0-9._:/-]{1,100}$/.test(value) ? value : undefined;
}

export class SessionBroker {
  private readonly leasesByKey = new Map<string, Lease>();
  private readonly leasesById = new Map<string, Lease>();

  constructor(private readonly spawnProcess: SpawnProcess = spawn, private readonly killGraceMs = 3_000) {}

  get activeCount(): number {
    return this.leasesById.size;
  }

  send(
    request: BrokerTurnRequest,
    emit: Emit,
    onCompleted?: () => void | Promise<void>,
    maxConcurrent?: number,
  ): SendTurnResult {
    const key = `${request.harness}:${request.conversationId}`;
    if (this.leasesByKey.has(key)) {
      return { accepted: false, message: "A turn is already running for this conversation." };
    }
    if (maxConcurrent !== undefined && this.activeCount >= Math.max(1, maxConcurrent)) {
      return { accepted: false, message: `Interactive capacity is full (${this.activeCount}/${Math.max(1, maxConcurrent)}). Wait for the active turn to finish.` };
    }
    const fallbackCommand = fallbackFor(request);
    const { args, executable } = brokerCommand(request);
    let child: ChildProcessWithoutNullStreams;
    try {
      child = this.spawnProcess(executable, args, {
        cwd: request.cwd,
        env: { ...process.env, NO_COLOR: "1" },
        shell: false,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (error) {
      return {
        accepted: false,
        message: error instanceof Error ? error.message : String(error),
        fallbackCommand,
      };
    }

    const lease: Lease = { id: randomUUID(), key, child, stopping: false, waiters: [] };
    this.leasesByKey.set(key, lease);
    this.leasesById.set(lease.id, lease);
    emit({ conversationId: request.conversationId, kind: "started" });

    let outputBuffer = "";
    let errorTail = "";
    let terminal = false;
    const handleLine = (line: string) => {
      if (!line.trim()) return;
      try {
        const parsed = JSON.parse(line) as Record<string, unknown>;
        const rawType = safeEventType(parsed.type);
        const isTextEvent = !rawType || /(?:assistant|agent|message|delta|content|stream_event)/i.test(rawType);
        const content = isTextEvent ? textualContent(parsed) : undefined;
        emit({
          conversationId: request.conversationId,
          kind: content ? "delta" : "tool",
          content,
          rawType,
        });
      } catch {
        // Provider stdout is untrusted. Unparseable lines are intentionally dropped.
      }
    };
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      outputBuffer += chunk;
      const lines = outputBuffer.split("\n");
      outputBuffer = lines.pop() ?? "";
      for (const line of lines) {
        handleLine(line);
      }
    });
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => {
      errorTail = `${errorTail}${chunk}`.slice(-1_000);
    });
    child.on("error", (error) => {
      if (terminal) return;
      terminal = true;
      this.release(lease);
      emit({
        conversationId: request.conversationId,
        kind: "error",
        content: error.message,
        fallbackCommand,
      });
    });
    child.on("close", async (code) => {
      if (terminal) return;
      terminal = true;
      handleLine(outputBuffer);
      if (code === 0) {
        try {
          await onCompleted?.();
          emit({ conversationId: request.conversationId, kind: "completed" });
        } catch (error) {
          emit({
            conversationId: request.conversationId,
            kind: "error",
            content: `Turn completed but GUI session state could not be persisted: ${error instanceof Error ? error.message : String(error)}`,
            fallbackCommand,
          });
        }
      } else {
        emit({
          conversationId: request.conversationId,
          kind: "error",
          content: safeProviderError(executable, errorTail, code),
          fallbackCommand,
        });
      }
      this.release(lease);
    });
    child.stdin.end(request.prompt);
    return {
      accepted: true,
      leaseId: lease.id,
      message:
        request.harness === "claude" && request.imported
          ? "Imported Claude session resumes under a single-writer lease; approval prompts may require Claude Code."
          : undefined,
      fallbackCommand,
    };
  }

  cancel(leaseId: string): boolean {
    const lease = this.leasesById.get(leaseId);
    if (!lease) return false;
    this.terminate(lease);
    return true;
  }

  async shutdown(): Promise<void> {
    await Promise.all(Array.from(this.leasesById.values(), (lease) => this.waitForTermination(lease)));
  }

  private terminate(lease: Lease): void {
    if (lease.stopping) return;
    lease.stopping = true;
    lease.killTimer = setTimeout(() => {
      if (this.leasesById.has(lease.id)) lease.child.kill("SIGKILL");
    }, this.killGraceMs);
    lease.child.kill("SIGTERM");
  }

  private waitForTermination(lease: Lease): Promise<void> {
    if (!this.leasesById.has(lease.id)) return Promise.resolve();
    return new Promise((resolve) => {
      lease.waiters.push(resolve);
      this.terminate(lease);
    });
  }

  private release(lease: Lease): void {
    if (lease.killTimer) clearTimeout(lease.killTimer);
    if (this.leasesByKey.get(lease.key)?.id === lease.id) this.leasesByKey.delete(lease.key);
    this.leasesById.delete(lease.id);
    for (const resolve of lease.waiters.splice(0)) resolve();
  }
}
