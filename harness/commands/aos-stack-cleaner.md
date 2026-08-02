# AOS Stack Cleaner

Use after a specific PR has merged and an operator wants to reclaim that one
worktree's fast-worktree containers, named volumes, and network.

Primary workflow: `harness/shared_factory/04-workflows/development_delivery/aos_stack_cleaner/`.

Run it manually and exact-item scoped. First complete the provider merge
readback, clean-worktree/unpushed-commit checks, target stack teardown, and
`os_cleanup` finalization. Then inspect the report-only Docker receipt:

```sh
harness/bin/agentic-os-docker-reclaim --root <os-root> --json
```

Apply only reviewed resources from that receipt:

```sh
harness/bin/agentic-os-docker-reclaim --root <os-root> --apply \
  --only <resource-name> --only <resource-name>
```

`--only` is intentionally exact-name only. Do not run a host-wide `--apply`
from this command, use `docker volume prune`, or include shared infra.
