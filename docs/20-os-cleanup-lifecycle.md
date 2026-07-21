# OS Cleanup Lifecycle

This page documents the OS cleanup workflow added in source commit `cf25145`
and installed into `/Users/genome/agentic_os` on 2026-06-15.

The goal is to keep Agentic OS project state clean after delivery work has
closed elsewhere. Worktrees and active work-item surfaces should stop appearing
as active once their Jira ticket reaches a terminal state or their attached
GitHub pull request is merged.

## Installed Surfaces

| Surface | Path |
| --- | --- |
| Workflow | `/Users/genome/agentic_os/harness/shared_factory/03-workflows/engineering/os_cleanup/` |
| Automation | `/Users/genome/agentic_os/harness/shared_factory/04-automations/engineering/closed_worktree_cleanup/` |
| Command doc | `harness/commands/os-clean-worktrees.md` |
| Skill | `harness/skills/os-cleaner/SKILL.md` |
| Codex adapter | `.agents/skills/os-cleaner/SKILL.md` |
| Runtime schedules | `closed_worktree_cleanup_0500` and `closed_worktree_cleanup_2200` in `harness/shared_factory/00-control-plane/runtime-registry.yml` |

The installed runtime schedules run daily at 05:00 and 22:00
`America/Chicago`. They remain registry-only cleanup schedules and must not pass
`--remove-files`.

## Primary Command

```sh
agentic-os project worktree cleanup-closed --root <os-root> --dry-run
agentic-os project worktree cleanup-closed --root <os-root> --apply
agentic-os project worktree cleanup-closed --root <os-root> --apply --remove-files
agentic-os project work-item infer-complete --root <os-root> --dry-run
agentic-os project work-item infer-complete --root <os-root> --apply
```

Use `--dry-run` first. Use `--apply` to move eligible registry entries out of
active state. Use `--remove-files` only after explicit approval or a written
guarded automation rule because it can delete local checkout directories. For
confirmed merged PR cleanup, local dirt is allowed unless root `REOPEN.md` is
present.

Use `infer-complete` before `finalize-lingering` when active work items appear
finished but still marked active in lifecycle state. The command treats stale-only work as
active; it needs terminal evidence plus completion artifacts plus clear
`NEXT.md` plus a quiet conversation window before it marks a packet `finished`.

## Candidate Signals

The command does not query Jira or GitHub directly. The workflow or automation
must refresh cached metadata first, then the command reads registered worktree
entries from:

- `config/worktrees.yml`
- `worktrees/index.yml`

A worktree is a cleanup candidate when one of these cached signals is present:

| Signal | Eligible values |
| --- | --- |
| Jira status | `QA Ready`, `Done`, `Ready for Production`, `Wont Do`, `Won't Do` |
| PR merged flag | `true`, `yes`, `1`, `merged`, `done` |
| PR state | `merged` |
| Worktree status | `merged`, `closed`, `archived`, `inactive`, or a terminal Jira-equivalent value |

Recognized Jira status fields include `jira_status`, `ticket_status`,
`issue_status`, `jira.status`, `jira.state`, and
`jira.fields.status.name`.

Recognized pull request fields include `pr_status`, `pull_request_status`,
`pr_state`, `pull_request_state`, `pr.status`, `pr.state`,
`pull_request.status`, `pull_request.state`, `github.pr.status`,
`github.pr.state`, `pr_merged`, `pull_request_merged`, `merged`,
`pr.merged`, `pull_request.merged`, and `github.pr.merged`.

Missing Jira or GitHub metadata is treated as active. The cleanup should log
the missing fields and leave the entry alone until a refresh proves closure.

## What Apply Does

`--apply` is registry cleanup, not physical deletion. For every eligible
worktree, it:

1. Writes or updates the entry in `<project>/worktrees/closed.yml`.
2. Adds `status: closed`, `closed_at`, `cleanup_reason`, and `cleanup_source`.
3. Removes the entry from the active registry.
4. Removes generated worktree symlinks when the entry has a `link` field.
5. Rebuilds `/Users/genome/agentic_os/00-control-plane/active/`.

Run this companion cleanup for stale work-item packets:

```sh
agentic-os project work-item infer-complete --root /Users/genome/agentic_os --dry-run
agentic-os project work-item infer-complete --root /Users/genome/agentic_os --apply
agentic-os project work-item finalize-lingering --root /Users/genome/agentic_os --apply
agentic-os project work-item sync-active --root /Users/genome/agentic_os
agentic-os validate --root /Users/genome/agentic_os
```

## File Removal Safety

Physical removal is intentionally separate:

```sh
agentic-os project worktree cleanup-closed --root /Users/genome/agentic_os --apply --remove-files
```

File removal only succeeds when all of these are true:

- The user or automation approval record explicitly allows file removal.
- The target path exists under the owning project's `worktrees/` directory.
- The target is a Git checkout.
- The cleanup reason is a confirmed merged PR, or `git status --porcelain` is
  clean.
- Root `REOPEN.md` is absent.

The command removes dirty merged-PR checkouts when `REOPEN.md` is absent.
Known disposable merged-PR dirt includes `.cursor/`, `.claude/`, `.features/`,
watch folders, `peak-styles.css`, and submodule state. The command skips dirty
unknown/unmerged checkouts and external paths. External checkouts can be closed
in the registry, but they are not deleted.

## Operator Runbook

1. Refresh cached Jira and GitHub metadata for registered worktrees.
2. Run:

   ```sh
   agentic-os project work-item infer-complete --root /Users/genome/agentic_os --dry-run
   agentic-os project worktree cleanup-closed --root /Users/genome/agentic_os --dry-run
   ```

3. Inspect candidate count, cleanup reasons, registry source paths, and skipped
   paths.
4. If candidates are correct, run:

   ```sh
   agentic-os project work-item infer-complete --root /Users/genome/agentic_os --apply
   agentic-os project worktree cleanup-closed --root /Users/genome/agentic_os --apply
   ```

5. Finalize related work-item packets and refresh the active surface:

   ```sh
   agentic-os project work-item finalize-lingering --root /Users/genome/agentic_os --apply
   agentic-os project work-item sync-active --root /Users/genome/agentic_os
   agentic-os validate --root /Users/genome/agentic_os
   ```

6. Write an automation log with candidate count, closed registry paths, removed
   paths, skipped paths, the active index path, and validation result.

## Current Installation Notes

The initial installed dry-run completed with `candidate_count=0`. That means no
registered worktree entry currently had cached terminal Jira or merged PR
metadata. It does not prove that every stale worktree is already clean.

The runtime entries are enabled for 05:00 and 22:00 `America/Chicago`, but they
only use registry cleanup. Capture reviewed dry-run evidence after the metadata
refresh step is wired for the projects that own the worktree registries.
