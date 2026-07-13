import { contextBridge, ipcRenderer } from "electron";
import { IPC, type AgenticOSApi, type GuiSnapshot, type SendTurnRequest, type StreamEvent } from "../shared/contracts";

const api: AgenticOSApi = {
  getUiConfig: () => ipcRenderer.invoke(IPC.uiConfig),
  getSnapshot: () => ipcRenderer.invoke(IPC.snapshot),
  getTranscript: (conversationId) => ipcRenderer.invoke(IPC.transcript, conversationId),
  setPinned: (conversationId, pinned) => ipcRenderer.invoke(IPC.setPinned, conversationId, pinned),
  sendTurn: (request: SendTurnRequest) => ipcRenderer.invoke(IPC.sendTurn, request),
  cancelTurn: (leaseId) => ipcRenderer.invoke(IPC.cancelTurn, leaseId),
  openExternal: (url) => ipcRenderer.invoke(IPC.openExternal, url),
  openLocalTarget: (conversationId, target, action) =>
    ipcRenderer.invoke(IPC.openLocalTarget, conversationId, target, action),
  onSnapshotChanged: (listener) => {
    const handler = (_event: Electron.IpcRendererEvent, snapshot: GuiSnapshot) => listener(snapshot);
    ipcRenderer.on(IPC.snapshotChanged, handler);
    return () => ipcRenderer.removeListener(IPC.snapshotChanged, handler);
  },
  onStreamEvent: (listener) => {
    const handler = (_event: Electron.IpcRendererEvent, streamEvent: StreamEvent) => listener(streamEvent);
    ipcRenderer.on(IPC.streamEvent, handler);
    return () => ipcRenderer.removeListener(IPC.streamEvent, handler);
  },
};

contextBridge.exposeInMainWorld("agenticOS", Object.freeze(api));
