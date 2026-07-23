---
schema_version: 1
id: alert
kind: trigger
title: Alert
priority: 15
applies_to:
  triggers: [alert]
evidence:
  - alert definition and threshold
  - firing and recovery timestamps
  - affected resource
  - baseline and recent changes
---

# Alert trigger

Verify that the alert represents a real user or system impact before diagnosing
the metric. Check threshold changes, missing telemetry, deployment timing, and
recovery behavior. Record whether the alert is causal, symptomatic, or noisy.
