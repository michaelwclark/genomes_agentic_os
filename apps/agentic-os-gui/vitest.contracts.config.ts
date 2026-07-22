import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["e2e/contracts/**/*.contract.ts"],
    testTimeout: 10_000,
  },
});
