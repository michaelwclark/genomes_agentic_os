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
| Runtime schedule | `closed_worktree_cleanup_prepare` in `harness/shared_factory/00-control-plane/runtime-registry.yml` |

The installed runtime schedule is disabled by default. Keep it disabled until
the Jira and GitHub metadata refresh step is proven for the target projects.

## Primary Command

```sh
agentic-os project worktree cleanup-closed --root <os-root> --dry-run
agentic-os project worktree cleanup-closed --root <os-root> --apply
agentic-os project worktree cleanup-closed --root <os-root> --apply --remove-files
```

Use `--dry-run` first. Use `--apply` to move eligible registry entries out of
active state. Use `--remove-files` only after explicit approval because it can
delete clean local checkout directories.

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
- `git status --porcelain` is clean.

The command skips dirty checkouts and external paths. External checkouts can be
closed in the registry, but they are not deleted.

## Operator Runbook

1. Refresh cached Jira and GitHub metadata for registered worktrees.
2. Run:

   ```sh
   agentic-os project worktree cleanup-closed --root /Users/genome/agentic_os --dry-run
   ```

3. Inspect candidate count, cleanup reasons, registry source paths, and skipped
   paths.
4. If candidates are correct, run:

   ```sh
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

Before enabling `closed_worktree_cleanup_prepare`, capture at least one
reviewed dry-run after the metadata refresh step is wired for the projects that
own the worktree registries.
