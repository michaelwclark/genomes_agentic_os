---
schema_version: 1
id: qa-failure
kind: trigger
title: Failed QA
priority: 15
applies_to:
  triggers: [qa-failure]
evidence:
  - scenario and acceptance criterion
  - test data and setup
  - observed and expected behavior
  - build and environment
  - prior passing evidence
---

# QA failure trigger

Determine whether the failure is product behavior, stale expectations, invalid
test data, environment drift, configuration, or test automation. Preserve the
exact scenario and compare with the most recent known pass.
