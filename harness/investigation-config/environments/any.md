---
schema_version: 1
id: any
kind: environment
title: Environment awareness
priority: 8
applies_to:
  environments: [any]
requirements:
  deployed_version: true
  environment_specific_evidence: true
failure:
  action: pause_same_run
  no_retry_storm: true
---

# Environment awareness

Environment-scoped evidence must name the environment, capture time, deployed
version authority, and relevant tenant or population. If VPN or the environment
is unavailable, record one pause receipt and a clear resume condition. Do not
burn repeated attempts guessing when access will return.
