---
schema_version: 1
id: log-entry
kind: trigger
title: Log entry
priority: 15
applies_to:
  triggers: [log-entry]
evidence:
  - exact timestamp and timezone
  - service and environment
  - request or correlation identifier
  - surrounding events
  - frequency and affected population
---

# Log entry trigger

One error line is a lead, not a root cause. Correlate the request across service
boundaries, bound frequency and blast radius, and distinguish the first causal
failure from downstream noise.
