/**
 * Contract test: @vitejs/plugin-react
 * Validates the API surface used by this project.
 *
 * Usage (electron.vite.config.ts): `react()` in the renderer plugins array.
 */
import react from "@vitejs/plugin-react";
import { describe, expect, it } from "vitest";

describe("@vitejs/plugin-react contract", () => {
  it("default export is a function", () => {
    expect(typeof react).toBe("function");
  });

  it("react() returns plugin object(s) with names, including a react plugin", () => {
    const result = react();
    const plugins = (Array.isArray(result) ? result.flat() : [result]).filter(
      (entry): entry is { name: string } =>
        Boolean(entry) && typeof (entry as { name?: unknown }).name === "string"
    );
    expect(plugins.length).toBeGreaterThan(0);
    expect(plugins.some((plugin) => plugin.name.includes("react"))).toBe(true);
  });
});
