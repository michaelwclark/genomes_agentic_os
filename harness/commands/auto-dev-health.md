# `/auto-dev-health`

Audit a delivered Auto-Dev work item, preserve everything needed to resume it,
and then remove only its reconstructable local resources. Use
`$auto-dev-health` with the existing work item's state:

```bash
agentic-os auto-dev health --state <work-item-or-autodev.json> --apply
```

Health always records `dirty_disposition: clean_only`. If the checkout is
dirty, Health preserves it and physical removal is blocked. Copying useful
evidence into the durable packet does not authorize deletion. Preserve or
reconcile the changes in a separate operator workflow, verify a clean
`git status --porcelain`, then rerun Health to create a fresh preflight.

The command writes and returns a packet-local Health preflight, ten-kind receipt
audit, resume manifest, and full pre-cleanup packet manifest. It does not delete
a runtime or worktree. Tear down the
exact runtime already registered from the project's `config/development.yml`,
using its recorded teardown and readback commands. Missing runtime registration
blocks cleanup; `not_managed` is valid only when the project explicitly declared
that it owns no per-worktree runtime. Managed identity contains domain, project,
and worktree, and both commands are identity-bound. Write the
`auto-dev-runtime-cleanup/v1` receipt bound to the preflight SHA-256. It must be
newer than the preflight and at most 15 minutes old; the cleanup gate immediately
runs the exact readback again, where exit 0 means only that registered runtime
is absent. Then pass both files with the exact domain, project, and worktree
selector to `project worktree cleanup-closed`. Preserve
the final two-resource readback as one `auto-dev-resource-cleanup/v1` receipt.
Then write a packet-local `auto-dev-closed-worktree-readback/v1` snapshot of
the exact live `worktrees/closed.yml` row, or `result: not_managed`. Audit that
snapshot under `resource_cleanup`; final Health cross-checks a managed entry
against live `closed.yml`.

Health never creates a work item, worktree, branch, container, or OrbStack
runtime. It runs only after verified delivery and Closeout, delegates cleanup
mechanics to `$os-cleaner`, and records the result from the packet's canonical
`03-complete` location.

The worktree gate matches registered id, path, branch, and current HEAD. It has
no force, Git-metadata-sweep, host-wide/all-resource, guessed-identity, or shared-runtime
path. After relocation every packet hash must match the pre-cleanup manifest
except semantic `work.yml` and `autodev.json` finished-state/path updates; those
two are parsed again. The finished packet is immutable history. Reopen canonical
work with a receipt and start a fresh delivery run for follow-up QA:

```bash
agentic-os auto-dev reopen --state <finished-packet-or-autodev.json> \
  --run-id <new-run-id> --reason "<QA or support reason>" --stage qa \
  --root <os-root> --apply
```

The reopen command creates one new active packet and fresh worktree/runtime
registration. It never changes the finished packet. The Health lane move itself
uses `project work-item set ... --state finished --health-relocation`, which
updates state-bearing metadata without appending to the packet-local worklog or
next-action files covered by the pre-cleanup manifest.

This command does not enable a schedule or provide a host-wide/all-resource mode. A
future automation may call the same item state and evidence contract without
owning a second lifecycle.
