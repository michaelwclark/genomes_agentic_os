---
schema_version: 1
id: tests-ci
kind: source
title: Tests and CI history
priority: 60
authority:
  class: executable regression evidence
freshness:
  mode: commit_and_run_bounded
tools:
  - local test runner
  - registered CI provider
evidence:
  - test identity and commit
  - command or CI job
  - pass/fail receipt
  - environment limitation
---

# Tests and CI

Use existing tests to explain intended behavior and historical regression
coverage. A passing unrelated suite is not disconfirming evidence. When local
execution is unavailable, use exact CI job receipts and name the limitation.
