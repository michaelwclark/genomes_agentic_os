---
name: os-health
description: Inspect Mac host speed risks and Agentic OS generated-artifact hygiene with observe-only reports and approval-gated cleanup classes.
---

# OS Health

Use when the user asks to investigate a sluggish Mac, heavy indexing, OrbStack or
runtime pressure, stale worktrees, or Agentic OS-generated logs, runs, artifacts,
and worklogs.

Canonical program: `harness/shared_factory/00-programs/host_agentic_os_health/`.

## Load

1. Route to the installed Agentic OS root and then to the owning project when a
   work item or worktree registry is named.
2. Read `harness/shared_factory/00-programs/host_agentic_os_health/program.md`
   when present.
3. Read `harness/commands/os-health.md` for the command contract.
4. Read `harness/commands/system-tool-registry.md` before non-trivial host
   inspection or cleanup.

## Workflow

1. Run an observe-only report:

   ```sh
   agentic-os health report --root <os-root> --output <work-item>/artifacts/health-report.yml
   ```

2. Review host pressure:
   - disk and memory
   - Spotlight/indexing status
   - hot processes
   - OrbStack status when available
3. Review Agentic OS pressure:
   - generated directories and sizes
   - registered worktrees and git state
   - active vs complete work-item locations
4. Separate follow-up actions:
   - `safe-auto`: allowed only by an approved policy
   - `approval-required`: ask before mutation
   - `manual-only`: user/operator handles directly
5. Use narrower cleanup commands only after their own dry-run report is reviewed.

## Docker / OrbStack reclamation

Per-worktree dev stacks leave a compose network and named volumes behind when
their worktree is deleted. Left alone they accumulate until Docker exhausts its
address pools and no new stack can start.

```sh
harness/bin/agentic-os-docker-reclaim --root <os-root>            # report (default)
harness/bin/agentic-os-docker-reclaim --root <os-root> --apply    # reclaim
```

Deletion requires **both**: no directory for the owning compose project under
any worktree root, and no attached container. Either predicate alone destroys
real state — "no running container" deletes the postgres volume of a merely
stopped worktree, and the worktree registry drifts too far to be trusted (every
registered LOS worktree reports `status: active`). Ambiguity keeps the resource.

Images and build cache are opt-in, not default. `docker volume prune` without
`-a` only removes anonymous volumes, so it never reclaims these named
per-worktree volumes.

A daily report-only schedule (`host_health_docker_reclaim`) writes receipts to
`harness/shared_factory/06-runs-and-logs/docker-reclaim/`. Review those before
arming `--apply`.

Do **not** move this into `$auto-dev-health`. That skill forbids host-wide
container/volume/network cleanup so per-item cleanup cannot touch resources it
does not own; the post-merge path is a chained host-scoped run after Health.

## Safety Rules

- Never delete files from this skill without explicit approval.
- Never stop or restart OrbStack, Docker, dev servers, launch agents, or runtime
  supervisors without explicit approval.
- Never disable Spotlight globally.
- Never remove dirty or untracked worktrees without path-specific approval.
- Keep local paths in internal receipts only.

## Output Contract

Report:

- report command and artifact path
- host bottleneck candidates
- generated artifact totals
- worktree totals
- approval-required actions
- skipped or unavailable checks
