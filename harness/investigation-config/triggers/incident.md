---
schema_version: 1
id: incident
kind: trigger
title: Incident
priority: 15
applies_to:
  triggers: [incident]
evidence:
  - impact window
  - detection and response timeline
  - affected users and systems
  - changes before onset
  - recovery action
---

# Incident trigger

Build a clock-consistent timeline. Separate trigger, root cause, contributing
conditions, detection gap, and recovery action. Preserve uncertainty and avoid
blame. A recovered service can still have an unresolved cause.
