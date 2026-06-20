---
name: os-cleaner
description: Keep Agentic OS worktree and work-item state clean after Jira terminal statuses or merged pull requests.
---

# OS Cleaner

Use when the user asks to clean, audit, or reconcile Agentic OS project worktrees, stateful directories, or stale work items after Jira or GitHub lifecycle closure.

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
   agentic-os project worktree cleanup-closed --root <os-root> --dry-run
   ```

3. If the dry-run candidates are correct, run:

   ```sh
   agentic-os project worktree cleanup-closed --root <os-root> --apply
   ```

4. Run `--remove-files` when the user has asked for physical checkout removal or the automation approval record explicitly allows it. For merged-PR cleanup, dirty status is not a blocker unless `REOPEN.md` exists.
5. Run:

   ```sh
   agentic-os project work-item finalize-lingering --root <os-root> --apply
   ```

6. Record candidate counts, closed registry path, removed merged worktrees, `REOPEN.md` holds, and active-container index path in the worklog or automation log.

## Safety Rules

- Never delete an external checkout path outside a project `worktrees/` directory.
- Never delete a reopened checkout with `REOPEN.md` without asking.
- For confirmed merged PRs, delete the worktree even when it contains local dirt such as `.cursor/`, `.claude/`, `.features/`, watch folders, `peak-styles.css`, or submodule state.
- Treat missing Jira/GitHub metadata as not eligible for automated cleanup.
- Registry cleanup is reversible from `worktrees/closed.yml`; physical deletion is not.
- External writes, Jira updates, and GitHub writes still require layer approval.

## Output Contract

Return:

- Cleanup mode and command run.
- Candidate count.
- Closed registry files.
- Removed symlinks or files.
- Skipped paths with reasons.
- Active container index path.
