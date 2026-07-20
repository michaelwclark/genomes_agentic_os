---
schema_version: 1
id: plan-and-gather
kind: phase
title: Plan and gather evidence
priority: 30
requirements:
  source_manifest: true
  freshness_recorded: true
  limitations_recorded: true
---

# Plan and gather

Rank sources by authority and cost. Start with durable local snapshots and
receipts, then use live read-only transports only for stale, missing, or
runtime-only facts. Record one bounded receipt per source with capture time,
freshness, facts, and limitations. Do not create a retry storm when VPN or a
provider is unavailable; pause the same run.
