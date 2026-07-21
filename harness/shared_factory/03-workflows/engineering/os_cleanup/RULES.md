# Rules

- Audit receipts and write the resume manifest before cleanup.
- Require explicit merge proof for physical code worktree removal.
- Keep `REOPEN.md`, failed teardown, failed removal, and ambiguous ownership
  visible and registered.
- Require a clean `git status --porcelain` for physical worktree removal. A
  dirty checkout always remains in place until a separate operator workflow
  reconciles it and Health is rerun.
- Use target-local teardown and exact Git worktree removal only.
- Never run a host-wide/all-resource Docker or OrbStack operation and never
  delete the packet.
- Never schedule Health or widen physical cleanup beyond one exact item.
