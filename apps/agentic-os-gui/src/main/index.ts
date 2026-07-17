import { app, BrowserWindow, ipcMain, shell } from "electron";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { readdir, realpath, stat } from "node:fs/promises";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import { AosBridge } from "./aosBridge";
import { OperatorStateStore } from "./operatorState";
import { SessionBroker } from "./sessionBroker";
import { WatchCoordinator } from "./watch";
import { IPC, type ConversationSummary, type GuiSnapshot, type StreamEvent } from "../shared/contracts";
import {
  isAllowedExternalUrl,
  isConversationId,
  validateOpenLocalTarget,
  validateSendTurn,
} from "../shared/validation";

let mainWindow: BrowserWindow | undefined;
let bridge: AosBridge;
let watchCoordinator: WatchCoordinator | undefined;
const broker = new SessionBroker();

// Keep the established state location stable across the user-facing product
// rename so existing pins, route overrides, and launched-session leases survive.
app.setPath("userData", join(app.getPath("appData"), "agentic-os-gui"));

function safeDisplayName(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const name = value.trim();
  return name && name.length <= 80 && !/[\u0000-\u001f\u007f]/.test(name) ? name : undefined;
}

function configuredDisplayName(): string {
  const fromArgs = process.argv.find((item) => item.startsWith("--aos-display-name="))?.slice("--aos-display-name=".length);
  const direct = safeDisplayName(fromArgs) ?? safeDisplayName(process.env.AGENTIC_OS_GUI_DISPLAY_NAME);
  if (direct) return direct;
  try {
    const settings = JSON.parse(readFileSync(join(app.getPath("userData"), "display.json"), "utf8")) as Record<string, unknown>;
    return safeDisplayName(settings.displayName) ?? "Command Center";
  } catch {
    return "Command Center";
  }
}

function configuredOperatorLabel(): string {
  try {
    const settings = JSON.parse(readFileSync(join(app.getPath("userData"), "display.json"), "utf8")) as Record<string, unknown>;
    return safeDisplayName(settings.operatorLabel) ?? "Operator";
  } catch {
    return "Operator";
  }
}

function trustedClaudeResumeId(conversation: ConversationSummary): string | undefined {
  if (isConversationId(conversation.cli_session_id)) return conversation.cli_session_id;
  if (isConversationId(conversation.continuation?.cli_session_id)) return conversation.continuation.cli_session_id;
  if (isConversationId(conversation.continuation?.session_id)) return conversation.continuation.session_id;
  const metadata = conversation.metadata;
  if (!metadata || typeof metadata !== "object") return undefined;
  for (const key of ["cli_session_id", "continuation_session_id", "resume_id", "session_id"]) {
    const candidate = metadata[key];
    if (isConversationId(candidate)) return candidate;
  }
  const continuation = metadata.continuation;
  if (continuation && typeof continuation === "object") {
    const candidate = (continuation as Record<string, unknown>).session_id;
    if (isConversationId(candidate)) return candidate;
  }
  return undefined;
}

function fixtureTurn(conversationId: string, emit: (event: StreamEvent) => void) {
  const leaseId = `fixture-${randomUUID()}`;
  queueMicrotask(() => {
    emit({ conversationId, kind: "started" });
    emit({ conversationId, kind: "delta", content: "Fixture mode accepted the routed turn." });
    emit({ conversationId, kind: "completed" });
  });
  return { accepted: true, leaseId };
}

function osRoot(): string {
  const fromArgs = process.argv.find((item) => item.startsWith("--aos-root="))?.slice("--aos-root=".length);
  return fromArgs || process.env.AGENTIC_OS_ROOT || join(app.getPath("home"), "agentic_os");
}

function isWithinRoot(root: string, candidate: string): boolean {
  const offset = relative(root, candidate);
  return offset === "" || (!offset.startsWith("..") && !isAbsolute(offset));
}

async function existingPathWithinRoot(root: string, candidate: string): Promise<string | undefined> {
  try {
    const [trustedRoot, trustedCandidate] = await Promise.all([realpath(root), realpath(candidate)]);
    if (!isWithinRoot(trustedRoot, trustedCandidate)) return undefined;
    const details = await stat(trustedCandidate);
    return details.isDirectory() || details.isFile() ? trustedCandidate : undefined;
  } catch {
    return undefined;
  }
}

async function trustedWorkItemPath(conversation: ConversationSummary, snapshot: GuiSnapshot): Promise<string> {
  const root = resolve(snapshot.root);
  const assetCandidates = (conversation.assets ?? [])
    .filter((asset) => asset.kind === "work-item" || asset.path.split("/").includes("work-items"))
    .flatMap((asset) => {
      const candidate = isAbsolute(asset.path) ? resolve(asset.path) : resolve(root, asset.path);
      if (!conversation.work_item) return asset.kind === "work-item" ? [candidate] : [];
      const parts = relative(root, candidate).split(sep);
      const workItemIndex = parts.indexOf(conversation.work_item);
      return workItemIndex >= 0 ? [resolve(root, ...parts.slice(0, workItemIndex + 1))] : [];
    });
  for (const candidate of assetCandidates) {
    const trusted = await existingPathWithinRoot(root, candidate);
    if (trusted) return trusted;
  }

  if (conversation.domain && conversation.project && conversation.work_item) {
    const workItemsRoot = resolve(root, conversation.domain, "02-projects", conversation.project, "work-items");
    if (isWithinRoot(root, workItemsRoot)) {
      try {
        for (const entry of await readdir(workItemsRoot, { withFileTypes: true })) {
          if (!entry.isDirectory()) continue;
          const candidate = resolve(workItemsRoot, entry.name, conversation.work_item);
          const trusted = await existingPathWithinRoot(root, candidate);
          if (trusted) return trusted;
        }
      } catch {
        // A routed work item may not have a local lifecycle folder yet.
      }
    }
  }
  throw new Error("conversation has no trusted local work-item path");
}

function createWindow(): BrowserWindow {
  const displayName = configuredDisplayName();
  const window = new BrowserWindow({
    width: 1500,
    height: 960,
    minWidth: 980,
    minHeight: 650,
    backgroundColor: "#0b0e13",
    title: displayName,
    show: false,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      devTools: !app.isPackaged,
    },
  });
  window.on("page-title-updated", (event) => {
    event.preventDefault();
    window.setTitle(displayName);
  });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event, target) => {
    const current = window.webContents.getURL();
    if (target !== current) event.preventDefault();
  });
  window.webContents.on("will-attach-webview", (event) => event.preventDefault());
  window.once("ready-to-show", () => window.show());
  if (!app.isPackaged && process.env.ELECTRON_RENDERER_URL) {
    void window.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    void window.loadFile(join(__dirname, "../renderer/index.html"));
  }
  return window;
}

function sendSnapshot(snapshot: GuiSnapshot): void {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(IPC.snapshotChanged, snapshot);
}

function registerIpc(store: OperatorStateStore): void {
  ipcMain.handle(IPC.uiConfig, () => ({
    displayName: configuredDisplayName(),
    operatorLabel: configuredOperatorLabel(),
  }));
  ipcMain.handle(IPC.snapshot, () => bridge.snapshot());
  ipcMain.handle(IPC.transcript, (_event, conversationId: unknown) => {
    if (!isConversationId(conversationId)) throw new Error("invalid conversation id");
    return bridge.transcript(conversationId);
  });
  ipcMain.handle(IPC.setPinned, async (_event, conversationId: unknown, pinned: unknown) => {
    if (!isConversationId(conversationId) || typeof pinned !== "boolean") throw new Error("invalid pin request");
    const conversation = await bridge.conversation(conversationId);
    if (!conversation) throw new Error("conversation is not present in the current Agentic OS snapshot");
    const state = await store.setPinned(`${conversation.harness}:${conversationId}`, pinned);
    bridge.invalidate();
    sendSnapshot(await bridge.snapshot(true));
    return state;
  });
  ipcMain.handle(IPC.sendTurn, async (_event, raw: unknown) => {
    const requested = validateSendTurn(raw);
    const conversation = await bridge.conversation(requested.conversationId);
    if (!conversation || conversation.harness !== requested.harness) throw new Error("conversation harness mismatch");
    const emit = (streamEvent: StreamEvent) => mainWindow?.webContents.send(IPC.streamEvent, streamEvent);
    if (process.env.AOS_GUI_FIXTURE === "1") return fixtureTurn(conversation.id, emit);

    const sourceKey = `${conversation.harness}:${conversation.id}`;
    const state = await store.read();
    const launched = state.launchedSessions[sourceKey];
    let resumeId = conversation.id;
    let newSessionId: string | undefined;
    let forkSession = false;
    if (conversation.harness === "claude") {
      if (launched) {
        resumeId = launched.sessionId;
      } else {
        const sourceResumeId = trustedClaudeResumeId(conversation);
        if (!sourceResumeId) {
          throw new Error("Claude Desktop conversation has no trusted CLI continuation session id");
        }
        resumeId = sourceResumeId;
        newSessionId = randomUUID();
        forkSession = true;
      }
    }
    const request = {
      ...requested,
      cwd: conversation.cwd,
      imported: Boolean(conversation.imported),
      resumeId,
      forkSession,
      newSessionId,
    };
    const result = broker.send(request, emit, async () => {
      if (conversation.harness === "claude") {
        const now = new Date().toISOString();
        await store.setLaunchedSession(sourceKey, launched ? { ...launched, updatedAt: now } : {
          harness: "claude",
          sessionId: newSessionId!,
          sourceConversationId: conversation.id,
          sourceResumeId: resumeId,
          createdAt: now,
          updatedAt: now,
          model: conversation.model,
          reasoningEffort: conversation.reasoning_effort,
        });
        bridge.invalidate();
        sendSnapshot(await bridge.snapshot(true));
      }
    });
    return result;
  });
  ipcMain.handle(IPC.cancelTurn, (_event, leaseId: unknown) => {
    if (typeof leaseId !== "string" || leaseId.length > 100) throw new Error("invalid lease id");
    return broker.cancel(leaseId);
  });
  ipcMain.handle(IPC.openExternal, async (_event, url: unknown) => {
    if (!isAllowedExternalUrl(url)) throw new Error("external URL is not allowlisted");
    await shell.openExternal(url);
    return true;
  });
  ipcMain.handle(IPC.openLocalTarget, async (_event, conversationId: unknown, target: unknown, action: unknown) => {
    const request = validateOpenLocalTarget(conversationId, target, action);
    const snapshot = await bridge.snapshot();
    const conversation = snapshot.conversations.find((item) => item.id === request.conversationId);
    if (!conversation) throw new Error("conversation is not present in the current Agentic OS snapshot");
    const path = await trustedWorkItemPath(conversation, snapshot);
    if (request.action === "finder") {
      shell.showItemInFolder(path);
    } else {
      const encodedPath = path.split(sep).map(encodeURIComponent).join("/");
      await shell.openExternal(`vscode://file${encodedPath}`);
    }
    return true;
  });
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow?.isMinimized()) mainWindow.restore();
    mainWindow?.focus();
  });
  void app.whenReady().then(() => {
    const store = new OperatorStateStore(join(app.getPath("userData"), "operator-state.json"));
    bridge = new AosBridge(osRoot(), () => store.read());
    registerIpc(store);
    mainWindow = createWindow();
    watchCoordinator = new WatchCoordinator(osRoot(), () => {
      bridge.invalidate();
      void bridge.snapshot(true).then(sendSnapshot).catch(() => undefined);
    });
    watchCoordinator.start();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) mainWindow = createWindow();
    });
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
let drainingForQuit = false;
app.on("before-quit", (event) => {
  watchCoordinator?.close();
  if (broker.activeCount && !drainingForQuit) {
    event.preventDefault();
    drainingForQuit = true;
    void broker.shutdown().finally(() => app.quit());
  }
});
