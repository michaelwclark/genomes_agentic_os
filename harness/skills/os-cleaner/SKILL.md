---
name: os-cleaner
description: Keep Agentic OS worktree and work-item state clean after Jira terminal statuses or merged pull requests.
---

# OS Cleaner

Use when the user asks to clean, audit, or reconcile Agentic OS project worktrees, stateful directories, or stale work items after Jira or GitHub lifecycle closure.

Canonical workflow: `harness/shared_factory/03-workflows/engineering/os_cleanup/`.
This skill is an invocation mirror for that workflow, not an independent policy
source.

## Load

1. Route to the owning project layer.
2. Read the project `worktrees/index.yml`, `worktrees/closed.yml` when present, and active work-item lanes.
3. Read the cleanup workflow or automation spec when running from `03-workflows` or `04-automations`.
4. Refresh Jira and GitHub state only through approved tools for the current layer.

## Workflow

1. Refresh cached metadata for registered worktrees:
   - Jira key or URL.
   - Jira status.
   - Pull request URL or number.
   - Pull request merged/state.
2. Run:

   ```sh
   agentic-os project work-item infer-complete --root <os-root> --dry-run
   agentic-os project worktree cleanup-closed --root <os-root> \
     [--domain <domain> --project <project> --worktree <exact-id-or-path>] \
     --dry-run
   ```

3. If the active work inference decisions are correct, run:

   ```sh
   agentic-os project work-item infer-complete --root <os-root> --apply
   ```

4. Choose one mutually exclusive apply path. For registry-only reconciliation,
   run the following and do not later try physical removal from the closed row:

   ```sh
   agentic-os project worktree cleanup-closed --root <os-root> \
     [--domain <domain> --project <project> --worktree <exact-id-or-path>] \
     --apply
   ```

   If physical removal is intended, skip the registry-only apply above. Run one
   guarded apply with `--remove-files` only after explicit merged-PR proof,
   packet-local Health preflight, item-local runtime teardown/readback bound to
   the preflight hash, useful `.features/` receipt preservation, and approval:

   ```sh
   agentic-os project worktree cleanup-closed --root <os-root> \
     --domain <domain> --project <project> --worktree <exact-id-or-path> \
     --health-preflight <packet>/artifacts/auto-dev-health/preflight.json \
     --runtime-receipt <packet>/artifacts/auto-dev-health/receipts/runtime-cleanup.json \
     --apply --remove-files
   ```

   The guarded command uses exact Git worktree removal and archives the row
   only after removal succeeds. A failed removal or
   `REOPEN.md` hold stays registered and active. Persist both final resource
   readbacks in one `auto-dev-resource-cleanup/v1` receipt.

5. Run:

   ```sh
   agentic-os project work-item finalize-lingering --root <os-root> --apply
   ```

6. Record inference decisions, candidate counts, closed registry path, removed merged worktrees, `REOPEN.md` holds, and active-container index path in the worklog or automation log.

## Safety Rules

- Never delete an external checkout path outside a project `worktrees/` directory.
- Auto-Dev Health always supplies `--domain`, `--project`, `--worktree`,
  `--health-preflight`, and `--runtime-receipt`; unscoped root sweeps are only
  for an explicitly requested registry-only audit and cannot remove files.
- Never delete a reopened checkout with `REOPEN.md` without asking.
- Tracker terminal state alone can close a registry entry but can never
  authorize physical checkout removal; code work requires explicit merge proof.
- Preserve useful local receipts before confirmed merged-PR cleanup. This does
  not authorize deletion of a dirty checkout: physical removal always requires
  a clean `git status --porcelain`. Reconcile dirty work through a separate
  operator workflow, then rerun Health. `REOPEN.md` always blocks.
- Treat missing Jira/GitHub metadata as not eligible for automated cleanup.
- Registry cleanup is reversible from `worktrees/closed.yml`; physical deletion is not.
- External writes, Jira updates, and GitHub writes still require layer approval.
- Auto-Dev Health is manual and exact-item scoped. Never turn this skill into a
  scheduled or host-wide/all-resource operation.

## Output Contract

Return:

- Cleanup mode and command run.
- Candidate count.
- Closed registry files.
- Removed symlinks or files.
- Skipped paths with reasons.
- Active container index path.
- Health preflight, preflight-bound runtime receipt, and atomic two-resource
  receipt when physical removal is in scope.
