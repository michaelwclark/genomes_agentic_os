/**
 * Contract test: electron-vite
 * Validates the API surface used by this project.
 *
 * Usage (electron.vite.config.ts): defineConfig({ main, preload, renderer })
 * with externalizeDepsPlugin() in main/preload; CLI drives dev/build scripts.
 */
import { defineConfig, externalizeDepsPlugin } from "electron-vite";
import { describe, expect, it } from "vitest";

describe("electron-vite contract", () => {
  it("defineConfig accepts the main/preload/renderer shape and preserves it", () => {
    const config = defineConfig({ main: {}, preload: {}, renderer: {} });
    expect(config).toBeTypeOf("object");
    for (const key of ["main", "preload", "renderer"] as const) {
      expect(config, `defineConfig dropped the '${key}' section`).toHaveProperty(key);
    }
  });

  it("externalizeDepsPlugin() returns a named plugin object", () => {
    const plugin = externalizeDepsPlugin() as { name?: unknown };
    expect(plugin).toBeTruthy();
    expect(typeof plugin.name).toBe("string");
    expect(String(plugin.name).length).toBeGreaterThan(0);
  });
});
