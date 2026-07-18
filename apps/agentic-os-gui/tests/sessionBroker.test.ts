import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import type { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { describe, expect, it } from "vitest";
import {
  brokerCommand,
  resolveProviderCli,
  SessionBroker,
  textualContent,
  type BrokerTurnRequest,
} from "../src/main/sessionBroker";

class FakeChild extends EventEmitter {
  stdin = new PassThrough();
  stdout = new PassThrough();
  stderr = new PassThrough();
  killedWith: NodeJS.Signals[] = [];

  kill(signal: NodeJS.Signals = "SIGTERM") {
    this.killedWith.push(signal);
    if (signal === "SIGKILL") queueMicrotask(() => this.emit("close", null));
    return true;
  }
}

function fakeSpawner(child: FakeChild): typeof spawn {
  return (() => child as unknown as ChildProcessWithoutNullStreams) as unknown as typeof spawn;
}

function request(overrides: Partial<BrokerTurnRequest> = {}): BrokerTurnRequest {
  return {
    conversationId: "local_source-id",
    harness: "claude",
    prompt: "continue",
    resumeId: "trusted-cli-session",
    ...overrides,
  };
}

describe("provider broker commands", () => {
  it("finds local provider CLIs without relying on a GUI PATH", () => {
    expect(resolveProviderCli("claude", undefined, "/Users/operator", (path) => path.endsWith("/.local/bin/claude")))
      .toBe("/Users/operator/.local/bin/claude");
    expect(resolveProviderCli("codex", undefined, "/Users/operator", (path) => path === "/Applications/ChatGPT.app/Contents/Resources/codex"))
      .toBe("/Applications/ChatGPT.app/Contents/Resources/codex");
  });

  it("resumes Codex with fixed argv and no shell", () => {
    expect(brokerCommand(request({ harness: "codex", conversationId: "source", resumeId: "trusted-codex" }), { CODEX_BIN: "/opt/codex" })).toEqual({
      executable: "/opt/codex",
      args: ["exec", "resume", "trusted-codex", "-", "--json", "--skip-git-repo-check"],
      continuationMode: "resume",
    });
  });

  it("forks the authoritative Claude CLI session exactly once into a GUI-owned id", () => {
    const command = brokerCommand(request({ forkSession: true, newSessionId: "11111111-1111-4111-8111-111111111111" }), { CLAUDE_BIN: "/opt/claude" });
    expect(command.executable).toBe("/opt/claude");
    expect(command.args).toContain("--verbose");
    expect(command.args).toEqual(expect.arrayContaining([
      "--resume", "trusted-cli-session",
      "--fork-session", "--session-id", "11111111-1111-4111-8111-111111111111",
    ]));
  });

  it("keeps the fork boundary in the first-turn fallback", () => {
    const child = new FakeChild();
    const broker = new SessionBroker(fakeSpawner(child));
    const result = broker.send(
      request({ forkSession: true, newSessionId: "11111111-1111-4111-8111-111111111111" }),
      () => undefined,
    );
    expect(result.fallbackCommand).toBe(
      "claude --resume trusted-cli-session --fork-session --session-id 11111111-1111-4111-8111-111111111111",
    );
    child.emit("close", 1);
  });

  it("resumes the persisted GUI-owned Claude session without another fork", () => {
    const command = brokerCommand(request({ resumeId: "11111111-1111-4111-8111-111111111111" }));
    expect(command.args).toEqual(expect.arrayContaining(["--resume", "11111111-1111-4111-8111-111111111111", "--verbose"]));
    expect(command.args).not.toContain("--fork-session");
    expect(command.args).not.toContain("--session-id");
  });

  it("rejects a fork without a destination session id", () => {
    expect(() => brokerCommand(request({ forkSession: true }))).toThrow("new session id");
  });

  it("extracts text only from known Codex and Claude streaming shapes", () => {
    expect(textualContent({ type: "item.completed", item: { type: "agent_message", text: "Codex reply" } })).toBe("Codex reply");
    expect(textualContent({ type: "stream_event", event: { type: "content_block_delta", delta: { type: "text_delta", text: "Claude delta" } } })).toBe("Claude delta");
    expect(textualContent({ type: "tool", payload: { secret: "never forward" } })).toBeUndefined();
  });

  it("persists a session mapping callback only after a successful CLI exit", async () => {
    const child = new FakeChild();
    const broker = new SessionBroker(fakeSpawner(child));
    let persisted = false;
    const events: string[] = [];
    broker.send(request(), (event) => events.push(event.kind), async () => { persisted = true; });
    expect(persisted).toBe(false);
    child.emit("close", 0);
    await new Promise((resolve) => setImmediate(resolve));
    expect(persisted).toBe(true);
    expect(events.at(-1)).toBe("completed");
  });

  it("does not persist a dead session id after a CLI failure", async () => {
    const child = new FakeChild();
    const broker = new SessionBroker(fakeSpawner(child));
    let persisted = false;
    broker.send(request(), () => undefined, () => { persisted = true; });
    child.emit("close", 1);
    await new Promise((resolve) => setImmediate(resolve));
    expect(persisted).toBe(false);
  });

  it("keeps the lease through cancellation, escalates, and drains on shutdown", async () => {
    const child = new FakeChild();
    const broker = new SessionBroker(fakeSpawner(child), 1);
    const result = broker.send(request(), () => undefined);
    expect(result.accepted).toBe(true);
    expect(broker.cancel(result.leaseId!)).toBe(true);
    expect(broker.send(request(), () => undefined).accepted).toBe(false);
    await broker.shutdown();
    expect(child.killedWith).toEqual(["SIGTERM", "SIGKILL"]);
    expect(broker.activeCount).toBe(0);
  });

  it("bounds concurrent manual turns to the reserved interactive capacity", () => {
    const first = new FakeChild();
    const children = [first, new FakeChild()];
    const broker = new SessionBroker((() => children.shift() as unknown as ChildProcessWithoutNullStreams) as unknown as typeof spawn);
    expect(broker.send(request({ conversationId: "one" }), () => undefined, undefined, 1).accepted).toBe(true);
    const blocked = broker.send(request({ conversationId: "two" }), () => undefined, undefined, 1);
    expect(blocked.accepted).toBe(false);
    expect(blocked.message).toContain("Interactive capacity is full");
    first.emit("close", 0);
  });

  it("preserves legacy cross-conversation concurrency when no fabric cap is supplied", () => {
    const children = [new FakeChild(), new FakeChild()];
    const broker = new SessionBroker((() => children.shift() as unknown as ChildProcessWithoutNullStreams) as unknown as typeof spawn);
    expect(broker.send(request({ conversationId: "legacy-one" }), () => undefined).accepted).toBe(true);
    expect(broker.send(request({ conversationId: "legacy-two" }), () => undefined).accepted).toBe(true);
  });
});
