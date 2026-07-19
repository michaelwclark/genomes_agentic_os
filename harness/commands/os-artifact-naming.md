# Durable Artifact Naming

Use the installed naming policy for top-level durable entities and run the
transactional migration when an older root must be normalized.

```bash
agentic-os naming show --root <os-root>
agentic-os naming migrate --root <os-root> --preflight
agentic-os naming migrate --root <os-root> --preflight \
  --recovery-backup-archive <existing-full-backup.tar.gz>
agentic-os naming migrate --root <os-root> --apply \
  --recovery-backup-archive <existing-full-backup.tar.gz>
agentic-os naming restore <receipt.json>
agentic-os naming restore <receipt.json> --apply
```

The default policy is enabled and uses `MMDDYY-` (`%m%d%y` plus `-`). It covers
work items, registered worktrees, conversation sidecars, async runs, run logs, report runs,
development runs, and thread closeouts. Stable files inside those entities do
not change names.

`migrate` is dry-run by default. `--preflight` inventories move, rewrite, and
backup costs and reports whether configured safety budgets permit an apply.
Apply refuses collisions and unsafe unacknowledged budgets, acquires an
orphan-recoverable mutation lock, creates a timestamped backup under
`~/backups/agentic_os`, journals every move, and emits atomic semantic progress
plus a terminal receipt. SIGINT and SIGTERM trigger rollback. Historical logs,
run evidence, completed work, snapshots, worktrees, and generated artifacts are
renamed when in scope but their contents remain immutable.

For a recovery continuation, pass the already-verified full backup with
`--recovery-backup-archive`; the new transaction then copies only mutable
references and records both backups. `--allow-high-risk` is an explicit
operator override, not a normal migration step. Run applies through
`agentic-os-quiet-run` with a wall-clock timeout.

Configuration: `harness/config/artifact-naming.yml`.
