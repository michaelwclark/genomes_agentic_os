---
schema_version: 1
id: deployed-version
kind: source
title: Deployed version authority
priority: 5
authority:
  class: domain-defined deployment authority
  rule: never infer from the default branch
freshness:
  mode: live_or_latest_deploy_receipt
prerequisites:
  - environment identity
evidence:
  - release or image version
  - git ref or commit when available
  - authority and capture time
failure:
  action: pause
  reasons: [provider_unavailable, environment_unavailable]
---

# Deployed version

Use the domain/project adapter to map the named environment to its exact running
version. The result gates code analysis. If there is no authoritative mapping,
record that as a blocker or uncertainty; never substitute `main`, `develop`, or
the newest local checkout.
