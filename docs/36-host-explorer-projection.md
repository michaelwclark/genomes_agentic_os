# Host Explorer Projection

The Command Center consumes one read-only, versioned host projection instead of
independently interpreting identity, routing, and run-log files. The CLI surface
is:

```bash
agentic-os host routing --root ~/agentic_os --recent-runs 20 --json
```

The response is `host-query/v1`. It joins each configured host's SSH identity,
routing role, concurrency limit, eligible harnesses, project paths, and latest
available harness-run receipt. It also returns the routing policy, artifact
return policy, memory-plane configuration, source paths, and diagnostics.

## Registry resolution

Installed roots may contain either of these layouts:

1. `config/hosts.yml` — the historical package and migration layout.
2. `harness/config/hosts.yml` — the harness-owned layout used by the installed
   cross-host runner.

The resolver uses an existing historical registry first when both exist, uses
the harness registry when it is the only installed source, and retains the
historical path for a fresh root. Updates always write back to the selected
existing registry; the CLI does not silently create a second source of truth.

## Health semantics

Host health is evidence-backed:

- `healthy`: the latest included harness-run receipt exited zero.
- `degraded`: the latest included receipt has a non-zero exit code.
- `unknown`: there is no included observation.

The projection never performs an SSH probe and never labels a configured host
healthy merely because it appears in YAML. Malformed identity or routing input
is represented in `diagnostics`; valid data from the other source remains
visible. This lets the GUI show partial state and a repair path instead of
failing the entire Hosts screen.

`agentic-os host list --json` provides the smaller `host-list/v1` identity-only
view for scripts that do not need routing or health.

## Safety boundary

The query is read-only. It does not connect to hosts, run commands, change
schedules, or dispatch work. Future live probes and remote actions must remain
explicit operator actions with their own receipts.

### Running this from Claude vs Codex

- **Claude:** invoke the same `agentic-os host routing ... --json` command from
  the installed OS contract.
- **Codex:** invoke the same CLI command directly; the JSON contract is harness
  neutral.

Both harnesses consume the same registries and receive the same projection.
