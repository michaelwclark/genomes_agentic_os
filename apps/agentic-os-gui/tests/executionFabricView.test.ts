import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { wrappedDialogFocusIndex } from "../src/renderer/components/ConversationList";
import { ExecutionFabricView, filterRuntimeTasks, taskSampleSummary } from "../src/renderer/components/ExecutionFabricView";
import { fixtureSnapshot } from "../src/shared/fixtures";

describe("Execution Fabric renderer behavior", () => {
  it("filters only the bounded snapshot sample by queue, status, and safe identifiers", () => {
    const tasks = fixtureSnapshot.runtime.tasks;
    expect(filterRuntimeTasks(tasks, "codex", "running", "codex_harness").map((task) => task.id)).toEqual([
      "task-codex-1",
    ]);
    expect(filterRuntimeTasks(tasks, "claude", "queued", "task-claude").map((task) => task.id)).toEqual([
      "task-claude-1",
    ]);
  });

  it("labels task results as a bounded sample instead of an exhaustive query", () => {
    expect(taskSampleSummary(fixtureSnapshot.runtime, 1)).toBe("1 shown from latest 2-task sample · 5 total");
  });

  it("wraps keyboard focus inside the modal at both tab boundaries", () => {
    expect(wrappedDialogFocusIndex(0, 4, true)).toBe(3);
    expect(wrappedDialogFocusIndex(3, 4, false)).toBe(0);
    expect(wrappedDialogFocusIndex(1, 4, false)).toBeUndefined();
  });

  it("renders accessible sampled filtering and a disabled refresh state", () => {
    const markup = renderToStaticMarkup(createElement(ExecutionFabricView, {
      runtime: fixtureSnapshot.runtime,
      onRefresh: async () => undefined,
      refreshing: true,
    }));
    expect(markup).toContain('aria-label="Search sampled tasks"');
    expect(markup).toContain("latest 2-task sample");
    expect(markup).toContain("Refreshing…");
    expect(markup).toContain("disabled");
  });
});
