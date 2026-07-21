# Approval rules: OS cleanup

- Dry-run, receipt audit, and readback are the default.
- Auto-Dev Health always requires a completed typed Merge receipt with merge
  SHA, provider-read source head equal to the reviewed revision, provider, PR
  reference, and verified readback, including no-resource/no-op outcomes.
- Only an explicitly non-code general OS Cleaner run may use its routed terminal
  evidence for registry-only closure; that result cannot satisfy Auto-Dev
  Health.
- Physical removal requires that typed Merge proof and an exactly matching
  Health terminal authority, known-root Git worktree metadata, absent `REOPEN.md`,
  preserved useful receipts, a clean `git status --porcelain`, and successful
  item-local runtime teardown. Preserved receipts do not authorize deleting a
  dirty checkout.
- A failed teardown or Git removal is a blocker. Keep the active registry entry
  so the resource remains visible and resumable.
- External checkouts, primary/protected branches, ambiguous runtimes, shared
  infrastructure, provider writes, and host-wide/all-resource operations are never
  implicitly approved.
- Health is manually invoked for one item. Scheduling physical cleanup or
  widening it beyond that item requires a different, explicitly designed
  workflow and is not authorized here.
