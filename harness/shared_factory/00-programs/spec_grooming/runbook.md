# Runbook: Spec Engine

## Operate

1. Resolve the layered policy and adapter authority.
2. Capture the raw request and intent anchors as a canonical Spec.
3. Run capability discovery and decide whether to extend, create under, or
   create new.
4. Write the packet with product, technical, state, flow, Gherkin, QA, rollout,
   assumptions, and open questions.
5. Create or synchronize provider records through the selected adapters.
6. Read back provider state and leave idempotent receipts in the packet.

## Recovery

- If discovery is inconclusive, stop with open questions instead of creating a
  parallel owner surface.
- If Notion workspace verification fails, skip Notion projection and record the
  blocker.
- If tracker writeback fails, preserve the local identity/provenance envelope,
  record a retryable receipt, and do not create a duplicate.
- If the request is LOS/Jira-primary, apply the LOS project policy before any
  backlog or active-sprint placement.
