# Durable Artifact Naming

Use the installed naming policy for top-level durable entities and run the
transactional migration when an older root must be normalized.

```bash
agentic-os naming show --root <os-root>
agentic-os naming migrate --root <os-root>
agentic-os naming migrate --root <os-root> --apply
agentic-os naming restore <receipt.json>
agentic-os naming restore <receipt.json> --apply
```

The default policy is enabled and uses `MMDDYY-` (`%m%d%y` plus `-`). It covers
work items, registered worktrees, conversation sidecars, async runs, run logs, report runs,
development runs, and thread closeouts. Stable files inside those entities do
not change names.

`migrate` is dry-run by default. Apply refuses collisions, creates a timestamped
backup under `~/backups/agentic_os`, moves Git worktrees with `git worktree
move`, rewrites filesystem and SQLite registry references, refreshes
`active-now.json`, and leaves a receipt under the shared run-log surface.

Configuration: `harness/config/artifact-naming.yml`.
