---
schema_version: 1
id: tracker
kind: source
title: Work tracker
priority: 30
authority:
  class: current work lifecycle
freshness:
  mode: live_readback
tools:
  - registered tracker connector or CLI
evidence:
  - current description and acceptance criteria
  - status, comments, links, and release fields
failure:
  action: pause_or_record_gap
  reasons: [provider_unavailable, authentication_unavailable]
---

# Work tracker

Use the live ticket or issue as current lifecycle truth. Preserve comment
authorship and timestamps. Do not assume a copied planning spec or chat excerpt
reflects the current acceptance criteria or status.
