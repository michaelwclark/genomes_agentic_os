import {
  Counter,
  Gauge,
  Histogram,
  Registry,
  collectDefaultMetrics,
} from "prom-client";
import type { LedgerPort } from "./ledger.js";
import type { PostgresReliabilityStore } from "./reliability.js";

export function createMetrics(prefix: string) {
  const registry = new Registry();
  collectDefaultMetrics({ register: registry, prefix });
  const admitted = new Counter({
    name: `${prefix}tasks_admitted_total`,
    help: "Tasks admitted to canonical PostgreSQL state",
    registers: [registry],
  });
  const assignments = new Counter({
    name: `${prefix}assignments_total`,
    help: "Worker assignments issued",
    registers: [registry],
  });
  const requestDuration = new Histogram({
    name: `${prefix}http_request_duration_seconds`,
    help: "HTTP request duration",
    labelNames: ["method", "route", "status"],
    registers: [registry],
  });
  const queueDepth = new Gauge({
    name: `${prefix}queue_depth`,
    help: "Canonical queued task count",
    labelNames: ["queue"],
    registers: [registry],
  });
  const running = new Gauge({
    name: `${prefix}queue_running`,
    help: "Canonical running task count",
    labelNames: ["queue"],
    registers: [registry],
  });
  const onlineWorkers = new Gauge({
    name: `${prefix}workers_online`,
    help: "Workers with unexpired registration leases",
    registers: [registry],
  });
  const findings = new Gauge({
    name: `${prefix}health_findings`,
    help: "Durable health finding count by lifecycle status",
    labelNames: ["status"],
    registers: [registry],
  });
  const alarmBacklog = new Gauge({
    name: `${prefix}alarm_outbox`,
    help: "Durable alarm count by delivery status",
    labelNames: ["status"],
    registers: [registry],
  });
  const repairs = new Gauge({
    name: `${prefix}repair_receipts`,
    help: "Deterministic healer receipt count by status",
    labelNames: ["status"],
    registers: [registry],
  });

  async function refresh(
    ledger: LedgerPort,
    reliability?: PostgresReliabilityStore,
  ): Promise<void> {
    const [queues, workers] = await Promise.all([
      ledger.queueSnapshot(),
      ledger.workerSnapshot(),
    ]);
    queueDepth.reset();
    running.reset();
    for (const queue of queues) {
      queueDepth.set({ queue: queue.queue }, queue.queued);
      running.set({ queue: queue.queue }, queue.running);
    }
    onlineWorkers.set(workers.filter((worker) => worker.state === "online").length);
    findings.reset();
    alarmBacklog.reset();
    repairs.reset();
    if (reliability) {
      const snapshot = await reliability.snapshot();
      for (const [status, count] of Object.entries(snapshot.findings)) {
        findings.set({ status }, count);
      }
      for (const [status, count] of Object.entries(snapshot.alarms)) {
        alarmBacklog.set({ status }, count);
      }
      for (const [status, count] of Object.entries(snapshot.repairs)) {
        repairs.set({ status }, count);
      }
    }
  }

  return {
    registry,
    admitted,
    assignments,
    requestDuration,
    refresh,
  };
}
