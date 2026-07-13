import { app, BrowserWindow, ipcMain, shell } from "electron";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import { AosBridge } from "./aosBridge";
import { OperatorStateStore } from "./operatorState";
import { SessionBroker } from "./sessionBroker";
import { WatchCoordinator } from "./watch";
import { IPC, type ConversationSummary, type GuiSnapshot, type StreamEvent } from "../shared/contracts";
import { isAllowedExternalUrl, isConversationId, validateSendTurn } from "../shared/validation";

let mainWindow: BrowserWindow | undefined;
let bridge: AosBridge;
let watchCoordinator: WatchCoordinator | undefined;
const broker = new SessionBroker();

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

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1500,
    height: 960,
    minWidth: 980,
    minHeight: 650,
    backgroundColor: "#0b0e13",
    title: "AgenticOSGui",
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
