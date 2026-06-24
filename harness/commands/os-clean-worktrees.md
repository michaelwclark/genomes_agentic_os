# OS Clean Worktrees

Use when project worktree state should be reconciled after Jira reaches a terminal delivery state or an attached GitHub pull request is merged.

Primary skill: `os-cleaner`.

Canonical workflow: `harness/shared_factory/03-workflows/engineering/os_cleanup/`.
This command doc is an invocation mirror, not an independent cleanup policy.

## CLI Surface

```sh
agentic-os project worktree cleanup-closed --root <os-root> --dry-run
agentic-os project worktree cleanup-closed --root <os-root> --apply
agentic-os project worktree cleanup-closed --root <os-root> --apply --remove-files
agentic-os project work-item infer-complete --root <os-root> --dry-run
agentic-os project work-item infer-complete --root <os-root> --apply
```

## Procedure

1. Route to the project that owns the worktree registry.
2. Refresh cached worktree metadata from Jira and GitHub before applying cleanup.
3. Run `agentic-os project work-item infer-complete --dry-run` first and inspect active work decisions.
4. Run `agentic-os project work-item infer-complete --apply` only for high-confidence completion decisions.
5. Run worktree `--dry-run` and inspect the candidate list.
6. Use worktree `--apply` to move terminal worktree registrations into `worktrees/closed.yml`, remove generated symlinks, and rebuild `00-control-plane/active/`.
7. Use `--remove-files` when in-project merged-PR worktree directories should be deleted. Dirty files are ignored for merged PR cleanup unless `REOPEN.md` is present.
8. Run `agentic-os project work-item finalize-lingering --apply` when related work-item packets have terminal statuses.
9. Record the cleanup result in the project worklog or automation log.

## Terminal Signals

Cleanup candidates are worktree entries with cached Jira status `QA Ready`, `Done`, `Ready for Production`, or `Wont Do`, or cached pull-request state `merged`.

Active work completion candidates are `02-active` packets with terminal evidence,
completion artifacts, clear `NEXT.md`, and no recent conversation activity.
Stale-only packets stay active.

## Safety

- The command does not query Jira or GitHub itself; the workflow refreshes those cached fields.
- Physical deletion requires `--remove-files` and a target under the project `worktrees/` directory.
- Merged-PR worktrees are removed even when dirty. Use `REOPEN.md` to preserve a reopened worktree for a follow-up PR.
- External worktree paths are closed in the registry but not deleted.
- Dirty non-merged checkouts are skipped and reported.
