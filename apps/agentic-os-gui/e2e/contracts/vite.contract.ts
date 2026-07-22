/**
 * Contract test: vite
 * Validates the API surface used by this project.
 *
 * vite is not imported directly by source; it is the engine under
 * electron-vite (dev/build) and vitest. This contract pins the programmatic
 * surface those tools and our configs rely on: defineConfig identity-preserving
 * behavior and a resolvable version.
 */
import { defineConfig, version } from "vite";
import { describe, expect, it } from "vitest";

describe("vite contract", () => {
  it("defineConfig({}) returns an object", () => {
    expect(defineConfig({})).toBeTypeOf("object");
  });

  it("defineConfig preserves config keys", () => {
    const config = defineConfig({ base: "./" }) as { base?: string };
    expect(config.base).toBe("./");
  });

  it("reports a semver version", () => {
    expect(version).toMatch(/^\d+\.\d+\.\d+/);
  });
});
