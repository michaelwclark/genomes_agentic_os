# OSProgram: Execution Fabric

## Purpose

Provide an optional, instance-wide execution fabric for named queues and bounded
worker pools so automations, workflows, programs, and interactive sessions can
share capacity without unbounded agent launches or unrelated work blocking one
global queue.

## Status

Installed and discoverable, but inactive by default. The compatibility mode is
the existing filesystem-backed YAML queue. Program presence never enables the
managed execution path.

## Ownership

The source package owns the reusable program contract, routing policy, queue and
worker-pool definitions, and activation requirements. Each installed Agentic OS
instance owns its selected mode, runtime state, receipts, and backend secrets.

## Modes

| Mode | Meaning |
| --- | --- |
| `filesystem` | Continue using the existing YAML run queue and runtime commands. |
| `execution_fabric` | Route admitted work through named managed queues and worker pools. |

Mode changes must be explicit, validated, reversible, and single-writer. A
future backend may use a local coordinator or an external workflow engine, but
producers consume the Agentic OS queue contract rather than a vendor API.

## Activation gate

Before `execution_fabric` is enabled, run the guarded queue-mode preflight. The
implementation enforces atomic claims, idempotent enqueue, bounded
global/provider/queue concurrency, leases and recovery, retry budgets, dead
letters, authoritative backend reads, health observability, self-heal routing,
system notifications, concurrent supervisor batches, interactive capacity
reservation, detached-child lease retention, and rollback blockers for
unprojected work.

Transient timeouts, provider throttling and 5xx responses, and recognized
network transport failures use bounded exponential backoff. Unknown command
failures remain terminal by default. The five-minute default supervisor cadence
keeps queue pickup within AutoDev's documented 5-10 minute expectation without
requiring an always-on broker on a laptop.

The supervisor also creates one daily online SQLite snapshot after validating
it with `PRAGMA integrity_check`; seven valid snapshots are retained under the
installed shared-factory run-log tree. Operators can request the same guarded
operation with `agentic-os state backup --root <root> --apply`.
