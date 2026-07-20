---
schema_version: 1
id: read-only-and-redaction
kind: safety
title: Read-only investigation boundary
priority: 1
safety:
  read_only_sources: true
  redact_secrets_and_customer_data: true
  sanitize_external_outputs: true
  verify_external_target: true
  require_external_readback: true
---

# Read-only and redaction boundary

Investigation authorizes inspection, not repair, data mutation, configuration
promotion, deployment, or ticket publication. Use the least-privileged query
that can answer the question. Never copy secrets, tokens, borrower/customer
data, local paths, or private workspace links into an external artifact.
Mutation requires the owning workflow and its approval gate.
