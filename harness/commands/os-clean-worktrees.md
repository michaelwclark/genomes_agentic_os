# OS Clean Worktrees

Use when project worktree state should be reconciled after Jira reaches a terminal delivery state or an attached GitHub pull request is merged.

Primary skill: `os-cleaner`.

Canonical workflow: `harness/shared_factory/03-workflows/engineering/os_cleanup/`.
This command doc is an invocation mirror, not an independent cleanup policy.

## CLI Surface

```sh
agentic-os project worktree cleanup-closed --root <os-root> --dry-run
agentic-os project worktree cleanup-closed --root <os-root> --apply
agentic-os project worktree cleanup-closed --root <os-root> \
  --domain <domain> --project <project> --worktree <exact-id-or-path> \
  --health-preflight <packet>/artifacts/auto-dev-health/preflight.json \
  --runtime-receipt <packet>/artifacts/auto-dev-health/receipts/runtime-cleanup.json \
  --apply --remove-files
agentic-os project work-item infer-complete --root <os-root> --dry-run
agentic-os project work-item infer-complete --root <os-root> --apply
```

## Procedure

1. Route to the project that owns the worktree registry.
2. Refresh cached worktree metadata from Jira and GitHub before applying cleanup.
3. Run `agentic-os project work-item infer-complete --dry-run` first and inspect active work decisions.
4. Run `agentic-os project work-item infer-complete --apply` only for high-confidence completion decisions.
5. Run worktree `--dry-run` and inspect the candidate list.
6. Choose registry-only closure or physical removal; do not run both in
   sequence. Registry-only `--apply` moves the row to `worktrees/closed.yml`.
7. For physical removal, skip registry-only apply and use one guarded
   `--apply --remove-files` for one exact in-project merged-PR worktree,
   only with domain, project, worktree, packet-local Health preflight, and a
   preflight-bound runtime receipt. Persist both resource results atomically.
   Physical removal requires a clean `git status --porcelain`. A dirty checkout
   is always preserved; reconcile it in a separate operator workflow and rerun
   Health after it is clean.
8. Run `agentic-os project work-item finalize-lingering --apply` when related work-item packets have terminal statuses.
9. Record the cleanup result in the project worklog or automation log.

## Terminal Signals

Cleanup candidates are worktree entries with cached Jira status `QA Ready`, `Done`, `Ready for Production`, or `Wont Do`, or cached pull-request state `merged`.

Active work completion candidates are canonical packets with terminal evidence,
completion artifacts, clear `NEXT.md`, and no recent conversation activity.
Stale-only packets stay active.

## Safety

- The command does not query Jira or GitHub itself; the workflow refreshes those cached fields.
- Physical deletion requires `--remove-files`, all five scoped Health inputs,
  and a target under the project `worktrees/` directory.
- Merge proof alone does not waive dirt. A dirty worktree always blocks
  physical removal, and `REOPEN.md` always blocks removal.
- External worktree paths are closed in the registry but not deleted.
- Dirty non-merged checkouts are skipped and reported.
- No Health schedule or host-wide/all-resource Docker/OrbStack operation is
  provided by this command.
