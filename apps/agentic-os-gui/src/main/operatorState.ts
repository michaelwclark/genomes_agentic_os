import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { LaunchedSession, OperatorState } from "../shared/contracts";

export const EMPTY_OPERATOR_STATE: OperatorState = {
  schemaVersion: 1,
  pinnedConversationIds: [],
  routeOverrides: {},
  launchedSessions: {},
};

function launchedSessions(value: unknown): Record<string, LaunchedSession> {
  if (!value || typeof value !== "object") return {};
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, LaunchedSession] => {
      const [, session] = entry;
      return Boolean(
        session &&
        typeof session === "object" &&
        (session as LaunchedSession).harness === "claude" &&
        typeof (session as LaunchedSession).sessionId === "string" &&
        typeof (session as LaunchedSession).sourceConversationId === "string" &&
        typeof (session as LaunchedSession).sourceResumeId === "string" &&
        typeof (session as LaunchedSession).createdAt === "string" &&
        typeof (session as LaunchedSession).updatedAt === "string",
      );
    }),
  );
}

export class OperatorStateStore {
  private mutationTail: Promise<void> = Promise.resolve();

  constructor(private readonly path: string) {}

  async read(): Promise<OperatorState> {
    try {
      const parsed = JSON.parse(await readFile(this.path, "utf8")) as Partial<OperatorState>;
      if (parsed.schemaVersion !== 1) return structuredClone(EMPTY_OPERATOR_STATE);
      return {
        schemaVersion: 1,
        pinnedConversationIds: Array.from(
          new Set((parsed.pinnedConversationIds ?? []).filter((item): item is string => typeof item === "string")),
        ).sort(),
        routeOverrides: parsed.routeOverrides && typeof parsed.routeOverrides === "object" ? parsed.routeOverrides : {},
        lastScope: parsed.lastScope,
        launchedSessions: launchedSessions(parsed.launchedSessions),
      };
    } catch {
      return structuredClone(EMPTY_OPERATOR_STATE);
    }
  }

  async write(state: OperatorState): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true });
    const temporary = `${this.path}.${process.pid}.${Date.now()}.tmp`;
    await writeFile(temporary, `${JSON.stringify(state, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
    await rename(temporary, this.path);
  }

  async setPinned(conversationId: string, pinned: boolean): Promise<OperatorState> {
    return this.mutate((state) => {
      const ids = new Set(state.pinnedConversationIds);
      if (pinned) ids.add(conversationId);
      else ids.delete(conversationId);
      return { ...state, pinnedConversationIds: Array.from(ids).sort() };
    });
  }

  async setLaunchedSession(sourceKey: string, launchedSession: LaunchedSession): Promise<OperatorState> {
    return this.mutate((state) => ({
      ...state,
      launchedSessions: { ...state.launchedSessions, [sourceKey]: launchedSession },
    }));
  }

  private async mutate(update: (state: OperatorState) => OperatorState): Promise<OperatorState> {
    let result: OperatorState | undefined;
    const operation = this.mutationTail.then(async () => {
      result = update(await this.read());
      await this.write(result);
    });
    this.mutationTail = operation.then(() => undefined, () => undefined);
    await operation;
    return result!;
  }
}
