import type { Harness, SendTurnRequest } from "./contracts";

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,199}$/;
const ALLOWED_HOSTS = [
  "github.com",
  "linear.app",
  "notion.so",
  "www.notion.so",
];

export function isConversationId(value: unknown): value is string {
  return typeof value === "string" && ID_PATTERN.test(value);
}

export function isHarness(value: unknown): value is Harness {
  return value === "codex" || value === "claude" || value === "unknown";
}

export function validateSendTurn(value: unknown): SendTurnRequest {
  if (!value || typeof value !== "object") throw new Error("send request must be an object");
  const request = value as Partial<SendTurnRequest>;
  if (!isConversationId(request.conversationId)) throw new Error("invalid conversation id");
  if (!isHarness(request.harness) || request.harness === "unknown") throw new Error("unsupported harness");
  if (typeof request.prompt !== "string" || !request.prompt.trim() || request.prompt.length > 100_000) {
    throw new Error("prompt must be between 1 and 100000 characters");
  }
  if (request.cwd !== undefined && (typeof request.cwd !== "string" || !request.cwd.startsWith("/"))) {
    throw new Error("cwd must be an absolute path");
  }
  return {
    conversationId: request.conversationId,
    harness: request.harness,
    prompt: request.prompt,
    cwd: request.cwd,
    imported: Boolean(request.imported),
  };
}

export function isAllowedExternalUrl(raw: unknown): raw is string {
  if (typeof raw !== "string" || raw.length > 4096) return false;
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.username || url.password) return false;
    return (
      ALLOWED_HOSTS.includes(url.hostname) ||
      url.hostname.endsWith(".atlassian.net") ||
      url.hostname.endsWith(".slack.com")
    );
  } catch {
    return false;
  }
}

export interface OpenLocalTargetRequest {
  conversationId: string;
  target: "work-item";
  action: "vscode" | "finder";
}

export function validateOpenLocalTarget(
  conversationId: unknown,
  target: unknown,
  action: unknown,
): OpenLocalTargetRequest {
  if (!isConversationId(conversationId)) throw new Error("invalid conversation id");
  if (target !== "work-item") throw new Error("unsupported local target");
  if (action !== "vscode" && action !== "finder") throw new Error("unsupported local action");
  return { conversationId, target, action };
}
