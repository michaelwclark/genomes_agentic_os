---
schema_version: 1
id: bug
kind: trigger
title: Reported bug
priority: 15
applies_to:
  triggers: [bug]
evidence:
  - observed behavior
  - expected behavior
  - reproduction or occurrence pattern
  - impact
  - environment and version
---

# Bug trigger

Reconstruct the smallest reproducible path. Treat the reported cause as a
hypothesis. Identify whether behavior is tenant-specific, environment-specific,
version-specific, data-specific, or universal before proposing a change.
