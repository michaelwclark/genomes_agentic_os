# OS Clean Worktrees

Use when project worktree state should be reconciled after Jira reaches a terminal delivery state or an attached GitHub pull request is merged.

Primary skill: `os-cleaner`.

## CLI Surface

```sh
agentic-os project worktree cleanup-closed --root <os-root> --dry-run
agentic-os project worktree cleanup-closed --root <os-root> --apply
agentic-os project worktree cleanup-closed --root <os-root> --apply --remove-files
```

## Procedure

1. Route to the project that owns the worktree registry.
2. Refresh cached worktree metadata from Jira and GitHub before applying cleanup.
3. Run `--dry-run` first and inspect the candidate list.
4. Use `--apply` to move terminal worktree registrations into `worktrees/closed.yml`, remove generated symlinks, and rebuild `00-control-plane/active/`.
5. Use `--remove-files` when in-project merged-PR worktree directories should be deleted. Dirty files are ignored for merged PR cleanup unless `REOPEN.md` is present.
6. Run `agentic-os project work-item finalize-lingering --apply` when related work-item packets have terminal statuses.
7. Record the cleanup result in the project worklog or automation log.

## Terminal Signals

Cleanup candidates are worktree entries with cached Jira status `QA Ready`, `Done`, `Ready for Production`, or `Wont Do`, or cached pull-request state `merged`.

## Safety

- The command does not query Jira or GitHub itself; the workflow refreshes those cached fields.
- Physical deletion requires `--remove-files` and a target under the project `worktrees/` directory.
- Merged-PR worktrees are removed even when dirty. Use `REOPEN.md` to preserve a reopened worktree for a follow-up PR.
- External worktree paths are closed in the registry but not deleted.
- Dirty non-merged checkouts are skipped and reported.
