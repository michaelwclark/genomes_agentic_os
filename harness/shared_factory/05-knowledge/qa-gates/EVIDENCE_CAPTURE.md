# Evidence Capture

Focus: proof outlives the session.

## Verify
- Every validation claim has a receipt: command + result + timestamp, test
  run link, screenshot, log excerpt, or data readback.
- Remote mutations are read back independently before being reported done.
- Evidence never includes secrets, tokens, or real PII beyond synthetic
  values.

## Evidence
- Receipts under the work item packet (artifacts/, logs/, HOLDOUT_QA_RESULTS,
  SUMMARY), timestamped; media carries a manifest line (filename, scenario,
  captured-at).
- Durable external summaries (PR body, tracker comment) carry the short
  team-visible form, never local paths.

Blocking: always (an unreceipted claim is not a validated claim).
