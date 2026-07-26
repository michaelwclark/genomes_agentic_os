# Acceptance Evidence

Focus: every acceptance criterion is proven, not asserted.

## Verify
- Map every AC (including gherkin scenarios and checklists) to code, a test,
  and, where user-visible, an exercised flow. `MISSING` mappings block.
- Negative-path and idempotency ACs are exercised explicitly (ownership not
  stolen, duplicates not created, retries converge).
- ACs verifiable only by manual action are flagged for human QA rather than
  silently marked covered.

## Evidence
- An AC map (criterion -> file:line + test + run evidence) in the work item
  packet; traceable in under a minute per criterion.
- Human-QA items enumerated in HOLDOUT_QA.md with expected outcomes;
  results recorded in HOLDOUT_QA_RESULTS.md.

Blocking: always.
