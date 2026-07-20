---
schema_version: 1
id: resolve-deployed-version
kind: phase
title: Resolve deployed version
priority: 20
prerequisites:
  - environment identity
requirements:
  version_before_code_analysis: true
---

# Resolve deployed version

For an environment-scoped report, identify the exact deployed release, tag,
branch, or commit using the domain's authority before reading code as evidence.
Do not silently substitute the default branch. If authority is unavailable,
pause with the missing dependency and resume condition.
