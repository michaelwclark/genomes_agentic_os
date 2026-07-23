---
schema_version: 1
id: normalize-and-scope
kind: phase
title: Normalize signal and scope
priority: 10
evidence:
  - original signal
  - reporter expectation
  - environment and tenant when relevant
  - time window
  - affected workflow or user
---

# Normalize and scope

Turn the report, ticket comment, failed QA result, alert, or log entry into one
testable question. Preserve exact identifiers and timestamps. Separate what was
observed from what the reporter believes caused it. State the likely blast
radius and the boundaries that remain unknown.
