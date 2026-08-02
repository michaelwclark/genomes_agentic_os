# AOS Stack Cleaner

Use this manual, exact-PR workflow after a pull request is merged to reclaim
that worktree's fast-worktree runtime without touching shared infrastructure or
another developer's stopped stack. It composes the existing item-scoped
`os_cleanup` workflow with the host-scoped Docker/OrbStack reclaim command.

## Inputs

- Provider-read merged PR number, repository, merge SHA, reviewed head SHA, and
  merge receipt.
- Exact managed worktree path plus its Health preflight and runtime receipt.
- Fast-worktree slug when the target ran a fast stack.

## Manual procedure

1. Read GitHub and the merge receipt. The provider source-head must equal the
   reviewed revision, and the PR must be merged. Missing evidence blocks.
2. Preserve useful local receipts, then check the exact worktree: no
   `REOPEN.md`, clean `git status --porcelain`, and no commits absent from its
   configured upstream. Dirty or unpushed work is a hold, not disposable data.
3. Tear down only the target fast stack (`make fast-down` from that worktree)
   and capture the runtime receipt. This stops its containers, drops its
   per-worktree database, flushes its namespaced cache keys, and releases its
   fast-worktree index. Never include `compose/infra.yml` in this teardown.
4. Run the existing exact-item `os_cleanup`/Health path. It finalizes the
   registry and removes the checkout only after all its scoped preconditions
   pass. A failed finalization keeps the checkout and stops this workflow.
5. Produce a Docker/OrbStack report after the worktree is gone:

   ```sh
   harness/bin/agentic-os-docker-reclaim --root <os-root> --json
   ```

   Select only resource names in that receipt that match the removed worktree
   and are marked `reclaim`. The command's safety predicate still requires no
   owner directory and no attached container.
6. Apply only those reviewed names, never the whole host plan:

   ```sh
   harness/bin/agentic-os-docker-reclaim --root <os-root> --apply \
     --only <target-network> --only <target-volume>
   ```

7. Read back the worktree finalization and Docker apply receipts. Record any
   refused Docker removal as a visible hold; do not retry by pruning broadly.

## Image and shared-infra policy

Container removal does not unmount an image. The fast Django workflow uses a
shared `los-django-local:shared` image, so it is outside per-PR cleanup.
Images and build cache remain manual, opt-in host-health work until their
ownership/retention policy is implemented. `los-infra_*`, `los-infra_network`,
shared database volumes, and `los_gold` are never targets of this workflow.

## Automation boundary

`pr.merged` may create a proposal or operator task only. It must not apply
teardown or removal until a durable GitHub event consumer provides an idempotent
key (`repository:pr_number:merge_sha`), lease, dead-letter handling, source-head
readback, and an approval-to-apply policy. The historical timer-based merge
cleanup is not an acceptable trigger.
