# Runbook: spec_grooming

## Operate

1. Capture the raw request and intent anchors.
2. Run doc-config and capability discovery.
3. Decide whether to extend, create under, or create new.
4. Write the packet with product, technical, state, flow, Gherkin, QA, rollout,
   assumptions, and open questions.
5. Project to Linear/Jira/Notion only after target verification and scrub.
6. Leave receipts in the packet.

## Recovery

- If discovery is inconclusive, stop with open questions instead of creating a
  parallel owner surface.
- If Notion workspace verification fails, skip Notion projection and record the
  blocker.
- If tracker writeback fails, keep the filesystem packet as source of truth and
  record the failed provider and error summary.
- If the request is LOS/Jira-primary, route to `$jira-product-orchestrator`.

