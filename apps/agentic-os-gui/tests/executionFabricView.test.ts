import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { wrappedDialogFocusIndex } from "../src/renderer/components/ConversationList";
import { snapshotFailureIsFatal } from "../src/renderer/App";
import {
  activeRuntimeAlarms,
  ExecutionFabricView,
  filterRuntimeTasks,
  humanizeIdentifier,
  operationalWorkers,
  runtimeAttentionCount,
  taskSampleSummary,
} from "../src/renderer/components/ExecutionFabricView";
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
    expect(filterRuntimeTasks(tasks, "all", "active", "release notes").map((task) => task.id)).toEqual([
      "task-claude-1",
    ]);
  });

  it("labels task results as a bounded sample instead of an exhaustive query", () => {
    expect(taskSampleSummary(fixtureSnapshot.runtime, 1)).toBe("1 shown from 2-task operational sample · 5 retained");
    expect(humanizeIdentifier("los_engineering_team_prs_ai_review_watcher")).toBe("LOS Engineering Team PRs AI Review Watcher");
  });

  it("wraps keyboard focus inside the modal at both tab boundaries", () => {
    expect(wrappedDialogFocusIndex(0, 4, true)).toBe(3);
    expect(wrappedDialogFocusIndex(3, 4, false)).toBe(0);
    expect(wrappedDialogFocusIndex(1, 4, false)).toBeUndefined();
    expect(wrappedDialogFocusIndex(-1, 4, false)).toBe(0);
    expect(wrappedDialogFocusIndex(-1, 4, true)).toBe(3);
  });

  it("keeps refresh failures non-fatal once a good snapshot exists", () => {
    expect(snapshotFailureIsFatal(false)).toBe(true);
    expect(snapshotFailureIsFatal(true)).toBe(false);
  });

  it("defensively hides hundreds of inactive legacy worker rows", () => {
    const offlineWorkers = Array.from({ length: 250 }, (_, index) => ({
      ...fixtureSnapshot.runtime.workers[0],
      id: `runtime-bigmac.example-4000-${index}`,
      status: "offline",
      active_tasks: 0,
      lease_until: "2026-07-12T18:30:00Z",
    }));
    const runtime = {
      ...fixtureSnapshot.runtime,
      registered_workers: 0,
      historical_worker_records: 0,
      workers: [...fixtureSnapshot.runtime.workers, ...offlineWorkers],
    };

    expect(operationalWorkers(runtime)).toHaveLength(1);
    const markup = renderToStaticMarkup(createElement(ExecutionFabricView, {
      runtime,
      onRefresh: async () => undefined,
      refreshing: false,
    }));
    expect(markup).toContain("250 inactive registrations hidden");
    expect(markup).not.toContain("runtime-bigmac.example-4000-249");
  });

  it("counts only actionable alarms, failed effects, drift, and failed healing", () => {
    const runtime = {
      ...fixtureSnapshot.runtime,
      dead_letter: 1,
      unhealthy_workers: 1,
      stale_queued: 1,
      expired_running_leases: 1,
      effects: { pending: 2, delivering: 1, delivered: 4, failed: 1, dead_letter: 1 },
      config: { ...fixtureSnapshot.runtime.config!, drifted: true },
      healing: { ...fixtureSnapshot.runtime.healing!, status: "failed" as const },
      alarms: [
        ...fixtureSnapshot.runtime.alarms!,
        { id: "active", severity: "critical" as const, status: "active" as const, message: "Leader unavailable" },
      ],
    };

    expect(activeRuntimeAlarms(runtime).map((alarm) => alarm.id)).toEqual(["active"]);
    expect(runtimeAttentionCount(runtime)).toBe(9);
  });

  it("renders accessible sampled filtering and a disabled refresh state", () => {
    const markup = renderToStaticMarkup(createElement(ExecutionFabricView, {
      runtime: fixtureSnapshot.runtime,
      onRefresh: async () => undefined,
      refreshing: true,
    }));
    expect(markup).toContain('aria-label="Search sampled tasks"');
    expect(markup).toContain("2-task operational sample");
    expect(markup).toContain("Refreshing…");
    expect(markup).toContain("Retrying / delayed");
    expect(markup).toContain("Control plane &amp; configuration");
    expect(markup).toContain("genomesbox");
    expect(markup).toContain("epoch 7");
    expect(markup).toContain("In sync");
    expect(markup).toContain("Effects, alarms &amp; healing");
    expect(markup).toContain("No active alarms");
    expect(markup).toContain("Recent run reports");
    expect(markup).toContain("Release notes review completed.");
    expect(markup).toContain("Heartbeat");
    expect(markup).toContain("Recent failures (1h)");
    expect(markup).toContain("Running now");
    expect(markup).toContain("Agentic OS GUI Review");
    expect(markup).toContain("Codex (LLM)");
    expect(markup).toContain("inactive registrations hidden");
    expect(markup).not.toContain("Most recently active 200");
    expect(markup).toContain("disabled");
    expect(markup).toContain('<option value="active" selected="">Active only</option>');
    expect(markup).toContain('value="blocked"');
    expect(markup).toContain('value="skipped"');
    expect(markup).toContain('value="dry-run"');
  });
});
