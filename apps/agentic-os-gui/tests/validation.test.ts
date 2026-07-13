import { describe, expect, it } from "vitest";
import {
  isAllowedExternalUrl,
  isConversationId,
  validateOpenLocalTarget,
  validateSendTurn,
} from "../src/shared/validation";

describe("IPC input validation", () => {
  it("accepts native and Claude Desktop local conversation ids", () => {
    expect(isConversationId("019f5a20-8209-7712-a43f-82936e31f835")).toBe(true);
    expect(isConversationId("local_294b3242-0ed8-4a22-afb0-c431150aa548")).toBe(true);
    expect(isConversationId("../../escape")).toBe(false);
  });

  it("does not confer trust on renderer model/session fields", () => {
    const value = validateSendTurn({
      conversationId: "local_294b3242-0ed8-4a22-afb0-c431150aa548",
      harness: "claude",
      prompt: "continue",
      resumeId: "attacker-session",
      newSessionId: "attacker-fork",
    });
    expect(value).toEqual({
      conversationId: "local_294b3242-0ed8-4a22-afb0-c431150aa548",
      harness: "claude",
      prompt: "continue",
      cwd: undefined,
      imported: false,
    });
  });

  it("allows only expected HTTPS work links", () => {
    expect(isAllowedExternalUrl("https://github.com/example/repo/pull/1")).toBe(true);
    expect(isAllowedExternalUrl("https://acme.atlassian.net/browse/ACME-1")).toBe(true);
    expect(isAllowedExternalUrl("https://acme.slack.com/archives/C1/p1")).toBe(true);
    expect(isAllowedExternalUrl("file:///etc/passwd")).toBe(false);
    expect(isAllowedExternalUrl("https://user:secret@github.com/example/repo")).toBe(false);
    expect(isAllowedExternalUrl("https://github.com.evil.example/phish")).toBe(false);
  });

  it("accepts only identifier-based local open intents", () => {
    expect(validateOpenLocalTarget("aos-client-session-001", "work-item", "vscode")).toEqual({
      conversationId: "aos-client-session-001",
      target: "work-item",
      action: "vscode",
    });
    expect(() => validateOpenLocalTarget("aos-client-session-001", "/etc", "finder")).toThrow(
      "unsupported local target",
    );
    expect(() => validateOpenLocalTarget("aos-client-session-001", "work-item", "rm -rf")).toThrow(
      "unsupported local action",
    );
  });
});
