---
schema_version: 1
id: logs-observability
kind: source
title: Logs and observability
priority: 40
authority:
  class: runtime observation
freshness:
  mode: time_window_bounded
prerequisites:
  - environment and time window
tools:
  - domain observability adapter
evidence:
  - query and time range
  - correlation identifiers
  - counts and representative events
  - telemetry limitations
failure:
  action: pause
  reasons: [vpn_unavailable, provider_unavailable]
---

# Logs and observability

Query the narrowest time window and service set that can test a hypothesis.
Capture counts, first/last occurrence, correlations, and missing telemetry.
Redact sensitive payloads. Do not equate absence of logs with absence of events.
