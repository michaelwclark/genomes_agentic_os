/**
 * Contract test: electron
 * Validates the API surface used by this project.
 *
 * In a plain Node/vitest process `require("electron")` resolves to the path of
 * the packaged binary (runtime APIs only exist inside an Electron process), so
 * this contract asserts: (1) the binary resolves and exists, (2) the installed
 * version matches the declared devDependency, and (3) electron's published
 * type surface still declares every API our main/preload processes use
 * (app, BrowserWindow, ipcMain, ipcRenderer, contextBridge, shell).
 */
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const appPackageJsonPath = fileURLToPath(new URL("../../package.json", import.meta.url));

describe("electron contract", () => {
  it("require('electron') resolves to an existing binary path in Node", () => {
    const electronPath = require("electron") as unknown;
    expect(typeof electronPath).toBe("string");
    expect((electronPath as string).length).toBeGreaterThan(0);
    expect(fs.existsSync(electronPath as string)).toBe(true);
  });

  it("installed version is valid semver and matches the declared devDependency major", () => {
    const electronPkg = require("electron/package.json") as { version: string };
    expect(electronPkg.version).toMatch(/^\d+\.\d+\.\d+/);

    const appPkg = JSON.parse(fs.readFileSync(appPackageJsonPath, "utf-8")) as {
      devDependencies: Record<string, string>;
    };
    const declared = appPkg.devDependencies.electron.replace(/^[\^~>=<\s]+/, "");
    expect(electronPkg.version.split(".")[0]).toBe(declared.split(".")[0]);
  });

  it("type surface still declares the APIs main/preload use", () => {
    const electronDir = path.dirname(require.resolve("electron/package.json"));
    const electronPkg = require("electron/package.json") as { types?: string };
    const dtsPath = path.join(electronDir, electronPkg.types ?? "electron.d.ts");
    const dts = fs.readFileSync(dtsPath, "utf-8");

    const modules = [
      "class BrowserWindow",
      "interface App",
      "interface IpcMain",
      "interface IpcRenderer",
      "interface ContextBridge",
      "interface Shell",
    ];
    const methods = [
      // app.*
      "whenReady",
      "requestSingleInstanceLock",
      "getPath",
      "setPath",
      "isPackaged",
      // BrowserWindow / webContents
      "getAllWindows",
      "setWindowOpenHandler",
      // ipcMain / ipcRenderer
      "handle",
      "invoke",
      "removeListener",
      // contextBridge / shell
      "exposeInMainWorld",
      "openExternal",
      "showItemInFolder",
    ];
    for (const declaration of [...modules, ...methods]) {
      expect(dts, `electron.d.ts no longer declares ${declaration}`).toContain(declaration);
    }
  });
});
