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
| Command doc | `harness/commands/os-clean-worktrees.md` |
| Skill | `harness/skills/os-cleaner/SKILL.md` |
| Codex adapter | `.agents/skills/os-cleaner/SKILL.md` |

Auto-Dev Health is manual and item-scoped. It does not install or enable a
schedule, run a host-wide/all-resource cleanup, or inherit physical-delete authority from
any general registry-maintenance schedule. A future monitor must invoke the
same item state and receipt gates explicitly.

## Primary Command

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

Use `--dry-run` first. Use `--apply` to move eligible registry entries out of
active state. Use `--remove-files` only after explicit approval or a written
guarded automation rule because it can delete local checkout directories.
Physical removal is always one-item scoped and requires domain, project,
worktree, packet-local Health preflight, and a runtime receipt bound to that
preflight SHA-256. The checkout must have a clean `git status --porcelain` at
the moment of removal. A dirty checkout always blocks Health physical cleanup;
merge proof and copied receipts do not waive that gate. Preserve or reconcile
the changes through a separate operator workflow, verify the checkout is clean,
then rerun Health from a fresh preflight.

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
agentic-os project worktree cleanup-closed --root <os-root> \
  --domain <domain> --project <project> --worktree <exact-id-or-path> \
  --health-preflight <packet>/artifacts/auto-dev-health/preflight.json \
  --runtime-receipt <packet>/artifacts/auto-dev-health/receipts/runtime-cleanup.json \
  --apply --remove-files
```

File removal only succeeds when all of these are true:

- The user or automation approval record explicitly allows file removal.
- `auto-dev-health-preflight/v1` is packet-local, current, and matches the
  exact domain, project, work item, worktree, merged revision, and receipt hashes.
- `auto-dev-runtime-cleanup/v1` is packet-local, matches the runtime identity,
  records verified readback, and binds `preflight_sha256`. Managed runtime
  identity contains domain/project/worktree and both commands are identity-
  bound. The receipt is newer than the preflight and at most 15 minutes old;
  the gate immediately executes the readback again, where exit 0 means the
  exact registered worktree runtime is absent.
- The target path exists under the owning project's `worktrees/` directory.
- The target is a Git checkout.
- Registered worktree id, path, branch, and current HEAD all match the task;
  HEAD equals the reviewed `subject_revision`.
- The provider-backed Health preflight proves a merged pull request and exact
  merge revision; a clean status is not merge authority.
- `git status --porcelain` is clean.
- Root `REOPEN.md` is absent.

The command does not infer that dirt is disposable from merge state or filename.
It always skips dirty checkouts. The operator must preserve or reconcile those
changes separately, make the checkout clean, and rerun Health with a newly
generated preflight. It also skips unmerged and external paths. External
checkouts can be closed in the registry, but they are not deleted.

Persist final worktree and runtime dispositions together in one packet-local
`auto-dev-resource-cleanup/v1` receipt. A later Health record points both
resource entries to that same atomic readback. Also preserve one packet-local
`auto-dev-closed-worktree-readback/v1` receipt: either the exact closed registry
row or `result: not_managed`. Final Health audits it as `resource_cleanup` and,
for a managed worktree, compares it with the live project
`worktrees/closed.yml` entry before completion.

Health also preserves a full pre-cleanup packet manifest. It hashes every
required, declared, and other durable packet file outside Health output. After
the finished-lane move every hash must match except semantic `work.yml` and
`autodev.json` state/path updates, which are parsed again. Final Health audits
ten exact kinds: `terminal_authority`, `closeout`, `receipt_audit`,
`resume_manifest`, `packet_manifest`, `resource_cleanup`, `runtime_cleanup`,
`work_state`, `active_index`, and `validation`.

Physical removal has no `--force`, Git metadata sweep, host-wide container-
resource operation, all-resource selector, guessed identity, or shared-runtime
path.

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

Auto-Dev Health remains manual, exact-item scoped, and receipt gated. It has no
scheduled or host-wide/all-resource mode. Runtime teardown is limited to the
exact registered item-local identity. A completed packet is immutable; follow-
up QA uses a receipt-backed canonical reopen and a new delivery run.
