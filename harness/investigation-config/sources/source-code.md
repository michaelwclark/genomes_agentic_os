---
schema_version: 1
id: source-code
kind: source
title: Version-matched source code
priority: 20
authority:
  class: version-controlled repository
  selection: deployed ref first
freshness:
  mode: immutable_commit
prerequisites:
  - deployed version when environment scoped
tools:
  - git
evidence:
  - exact file and symbol
  - commit or tag
  - executable behavior and tests
---

# Source code

Inspect the code that actually ran. Trace entrypoint, validation, state change,
side effects, error handling, and tests. Use current code only as comparison
unless it matches the deployed ref. Cite narrow symbols and behavior rather than
large code dumps.
